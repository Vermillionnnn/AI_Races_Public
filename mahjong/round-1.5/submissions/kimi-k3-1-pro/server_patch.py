"""旧启动入口的兼容包装。

正式入口是：python3 server.py --port 8000
此文件不再复制接口转换逻辑，避免两份实现再次出现差异。
"""

from server import main


if __name__ == "__main__":
    main()
