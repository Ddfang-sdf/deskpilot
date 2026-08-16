"""PyInstaller 打包入口：python -m deskpilot 的等价脚本。"""

from deskpilot.main import main

raise SystemExit(main())
