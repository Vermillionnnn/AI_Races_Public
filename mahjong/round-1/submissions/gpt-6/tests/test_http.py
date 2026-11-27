import json
import threading
import unittest
from http.client import HTTPConnection

from game import make_wall
from server import MahjongHandler, MahjongServer

from fixtures import wall_with


class QuietHandler(MahjongHandler):
    def log_message(self, *_):
        pass


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = MahjongServer(('127.0.0.1', 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def request(self, method, path, payload=None, status=200):
        body = json.dumps(payload) if payload is not None else None
        connection = HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            data = response.read()
            self.assertEqual(response.status, status, data)
            self.assertEqual(response.getheader('Access-Control-Allow-Origin'), '*')
            if response.getheader('Content-Type', '').startswith('application/json'):
                data = json.loads(data)
                if status >= 400:
                    self.assertIsInstance(data['error'], str)
            return data
        finally:
            connection.close()

    def start(self, **kwargs):
        return self.request('POST', '/api/new_game', {'players': ['human'] * 4, **kwargs})

    def state(self, game_id, seat):
        return self.request('GET', f'/api/state?game_id={game_id}&seat={seat}')

    def action(self, game_id, seat, kind, *, status=200, **kwargs):
        return self.request('POST', '/api/action', {'game_id': game_id, 'seat': seat, 'type': kind,
                                                    **kwargs}, status=status)

    def test_page_and_preflight(self):
        self.assertIn('开局规则'.encode(), self.request('GET', '/'))
        self.assertEqual(self.request('OPTIONS', '/api/action', status=204), b'')

    def test_game_id_rules_invalid_requests_and_view_privacy(self):
        wall = wall_with(draws=['6m'], dead={122: '7z'}, red=False)
        first = self.start(wall=wall, rules={'aka_dora': False, 'renpu_fu': 2})
        game_id = first['game_id']
        self.assertEqual(first['rules'], {'aka_dora': False, 'kuitan': True,
                                          'kiriage_mangan': False, 'renpu_fu': 2})
        self.assertEqual(first['drawn'], '6m')
        self.assertEqual(first['players'][0]['hand_count'], 13)
        self.assertEqual(first['events'], [{'type': 'draw', 'seat': 0, 'tile': '6m'}])
        self.assertEqual(first['dora_indicators'], ['7z'])
        other = self.state(game_id, 1)
        self.assertIsNone(other['drawn'])
        self.assertNotIn('hand', other['players'][0])
        self.assertEqual(other['players'][0]['hand_count'], 13)
        self.assertEqual(other['events'], [{'type': 'draw', 'seat': 0, 'tile': None}])
        self.assertEqual(other['legal_actions'], [])
        self.action(game_id, 1, 'discard', tile='6m', status=400)
        self.action(game_id, 0, 'discard', tile='0p', status=400)
        self.action(game_id, False, 'discard', tile='6m', status=400)
        self.request('GET', f'/api/state?game_id={game_id}&seat=-1', status=400)
        self.request('POST', '/api/next', {'game_id': game_id, 'seat': 0}, status=400)
        self.request('POST', '/api/new_game', {'rules': {'kuitan': 1}}, status=400)
        self.request('POST', '/api/new_game', {'rules': {'aka_dora': False}, 'wall': make_wall()}, status=400)
        self.assertEqual(self.state(game_id, 0), first)

        second = self.start(seed=7)
        self.assertNotEqual(second['game_id'], game_id)
        self.request('GET', f'/api/state?game_id={game_id}&seat=0', status=404)
        self.action(game_id, 0, 'discard', tile='6m', status=404)
        self.request('POST', '/api/next', {'game_id': game_id, 'seat': 0}, status=404)

    def test_tsumogiri_flag_distinguishes_same_tile(self):
        wall = wall_with({0: ['6m']}, ['6m'])
        for tsumogiri in (False, True, None):
            with self.subTest(tsumogiri=tsumogiri):
                start = self.start(wall=wall)
                game_id = start['game_id']
                other = next(t for t in start['players'][0]['hand'] if t != '6m')
                self.action(game_id, 0, 'discard', tile=other, tsumogiri=True, status=400)
                self.assertEqual(self.state(game_id, 0), start)
                flags = {} if tsumogiri is None else {'tsumogiri': tsumogiri}
                result = self.action(game_id, 0, 'discard', tile='6m', **flags)
                discard, = result['players'][0]['discards']
                self.assertEqual(discard, {'tile': '6m', 'riichi': False, 'called': False,
                                           'tsumogiri': tsumogiri is not False})
                self.assertEqual(result['events'][1]['tsumogiri'], tsumogiri is not False)
                self.assertIn('6m', result['players'][0]['hand'])

    def test_wait_for_both_calls_then_pon_takes_priority_over_chi(self):
        wall = wall_with({1: ['3m', '4m'], 2: ['5m', '5m', '0m']}, ['5m'], {122: '8p'})
        first = self.start(wall=wall)
        game_id = first['game_id']
        result = self.action(game_id, 0, 'discard', tile='5m')
        self.assertEqual(result['waiting_for'], [1, 2])
        choices = {a['type']: a for a in self.state(game_id, 2)['legal_actions']}
        self.assertEqual(choices['pon']['options'], [['5m', '5m'], ['5m', '0m']])
        self.assertIn('minkan', choices)
        after_chi = self.action(game_id, 1, 'chi', tiles=['3m', '4m'])
        self.assertEqual(after_chi['waiting_for'], [2])
        self.assertEqual(after_chi['legal_actions'], [])
        self.action(game_id, 1, 'pass', status=400)
        after_pon = self.action(game_id, 2, 'pon', tiles=['0m', '5m'])
        self.assertEqual(after_pon['waiting_for'], [2])
        self.assertIsNone(after_pon['drawn'])
        self.assertTrue(after_pon['players'][0]['discards'][0]['called'])
        self.assertEqual(after_pon['players'][2]['melds'], [
            {'type': 'pon', 'tiles': ['5m', '5m', '0m'], 'from': 0, 'called_tile': '5m'}])
        self.assertEqual(after_pon['events'][-1]['type'], 'pon')
        self.assertIn('5m', after_pon['players'][2]['hand'])
        self.assertNotIn('5m', after_pon['legal_actions'][0]['tiles'])
        self.assertNotIn('5m', after_pon['hints']['discards'])

    def test_result_and_next_wall_use_fixed_physical_seats(self):
        first = self.start(players=['bot'] * 4, length='hanchan', seed=13, rules={'aka_dora': False})
        game_id = first['game_id']
        self.assertEqual(first['phase'], 'round_end')
        self.assertEqual(first['result']['reason'], 'exhaustive')
        self.assertFalse(first['result']['tenpai'][0])
        next_wall = wall_with({0: ['9m', '9m'], 1: ['7z', '7z']}, ['8m'], {122: '6s'}, red=False)
        self.request('POST', '/api/next', {'game_id': game_id, 'seat': 1, 'wall': ['1m'] * 136}, status=400)
        self.assertEqual(self.state(game_id, 0), first)
        next_state = self.request('POST', '/api/next', {'game_id': game_id, 'seat': 1, 'wall': next_wall})
        self.assertEqual(next_state['round']['dealer'], 1)
        self.assertEqual(next_state['round']['honba'], 1)
        self.assertEqual(next_state['players'][1]['hand'].count('7z'), next_wall[13:26].count('7z'))
        self.assertEqual(next_state['players'][1]['seat_wind'], '1z')
        self.assertEqual(next_state['dora_indicators'], ['6s'])
        self.assertEqual(next_state['events'][0], {'type': 'draw', 'seat': 1, 'tile': '8m'})
        self.assertFalse(next_state['rules']['aka_dora'])


if __name__ == '__main__':
    unittest.main()
