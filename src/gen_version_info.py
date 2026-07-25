# -*- coding: utf-8 -*-
"""Vygeneruje version_info.txt pro PyInstaller z APP_VERSION v gui.py.

Spouští build_live.bat před PyInstallerem; výsledek se zapíše do
Details tabu vlastností exe (File description, verze, copyright...).
"""
import re

src = open("gui.py", encoding="utf-8").read()
ver = re.search(r'APP_VERSION = "([^"]+)"', src).group(1)
nums = [int(x) for x in re.findall(r"\d+", ver)][:4]
nums += [0] * (4 - len(nums))
tup = tuple(nums)

TEMPLATE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=%(tup)s,
    prodvers=%(tup)s,
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('FileDescription', 'Manage & edit your TW: Warhammer 3 SP & MP saved games'),
         StringStruct('FileVersion', '%(ver)s'),
         StringStruct('ProductName', 'WH3 Save Editor'),
         StringStruct('ProductVersion', '%(ver)s'),
         StringStruct('CompanyName', 'davehornik'),
         StringStruct('LegalCopyright', '© davehornik@github — unofficial fan tool, not affiliated with CA/SEGA/Games Workshop'),
         StringStruct('OriginalFilename', 'WH3SaveEditor.exe'),
         StringStruct('Comments', 'https://github.com/davehornik/WH3SaveEditor')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

open("version_info.txt", "w", encoding="utf-8").write(
    TEMPLATE % {"tup": tup, "ver": ver})
print("version_info.txt pro v%s %s" % (ver, tup))
