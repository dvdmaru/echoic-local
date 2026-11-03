# PyInstaller runtime hook：在載入 tkinter 之前把 LC_CTYPE 設成 UTF-8。
#
# 為什麼：從 Finder 雙擊打開 App 時，macOS 不帶 LANG／LC_*，程序的 locale 是 C（US-ASCII）。
# 內附的 Tcl 8.6 用這個編碼去讀 App 路徑，「Echoic 本機版.app」裡的中文會被讀壞，
# 於是找不到 _tcl_data/init.tcl，視窗開不起來就直接結束（2026-11-03 Charlie 實機回報，
# 錯誤是 "Can't find a usable init.tcl … list element in braces followed by …"）。
# 從終端機啟動有 LANG，所以 11/1 的驗收沒測到。Info.plist 的 LSEnvironment 是第一層，這裡是第二層。
import locale
import os

if not any(os.environ.get(k) for k in ("LC_ALL", "LC_CTYPE", "LANG")):
    os.environ["LC_CTYPE"] = "UTF-8"
try:
    locale.setlocale(locale.LC_CTYPE, "UTF-8")
except locale.Error:
    pass
