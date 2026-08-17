"""PyInstaller 打包入口：python -m deskpilot 的等价脚本。

冻结形态下兼作审批弹窗子进程入口：
  deskpilot.exe --approval-dialog <desc_path> <result_path> <timeout>
（TkApprovalChannel 在非冻结形态用 python -m deskpilot.approval_dialog 拉起弹窗；
onefile 下 sys.executable 是本 exe 自身，-m 参数无效，须由此分发。）
"""

import sys

if sys.argv[1:2] == ["--approval-dialog"]:
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    from deskpilot.approval_dialog import main as dialog_main
    dialog_main()
else:
    from deskpilot.main import main
    raise SystemExit(main())
