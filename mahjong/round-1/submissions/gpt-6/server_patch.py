# 指导老师的临时入口，沿用同一个网页接口实现。
import os

from server import main


if __name__ == '__main__':
    main(default_port=int(os.environ.get('PORT', '5000')))
