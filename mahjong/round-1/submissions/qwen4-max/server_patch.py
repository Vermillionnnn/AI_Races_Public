# 指导老师的补丁（已并入 server.py，本文件仅作兼容入口保留）
#
# qwen4-max 说明：原来这个补丁是为了把 250226 的 server.py 输出硬掰成前端格式，
# 还要靠 YAKU_HAN 表猜每役番数。现在 server.py 已直接按《接口说明》实现、
# yaku.py 也返回每役真实番数，补丁里的转换都不需要了。
# 为兼容旧启动方式，`python3 server_patch.py` 直接转调 server.main()。

import server

if __name__ == '__main__':
    server.main()