# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = ['mcp.server.stdio', 'mcp.server.lowlevel', 'mcp.types']
hiddenimports += collect_submodules('uiautomation')
hiddenimports += collect_submodules('comtypes.gen')
# rapidocr 在运行期动态 import 各模型模块（ch_ppocr_v3_det 等），须全部收集
hiddenimports += collect_submodules('rapidocr_onnxruntime')

# uiautomation 运行期从 <pkg>/bin 以 add_dll_directory 加载
# UIAutomationClient_VC140_*.dll（数据文件，须显式收集，否则 onefile 下 UIA 失效）；
# rapidocr_onnxruntime 的 config.yaml 与 ONNX 模型同为数据文件。
datas = collect_data_files('uiautomation') + collect_data_files('rapidocr_onnxruntime')


a = Analysis(
    ['run_deskpilot.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='deskpilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
