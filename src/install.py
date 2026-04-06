"""
install.py — Windows 레지스트리 우클릭 메뉴 등록/해제 (HKCU, 관리자 권한 불필요)
"""
import sys
import winreg


def _get_exe_path() -> str:
    """PyInstaller frozen 환경이면 sys.executable, 아니면 sys.argv[0] 절대경로."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return str(__import__("pathlib").Path(sys.argv[0]).resolve())


def _set_key(base: int, key_path: str, values: dict[str, str]) -> None:
    """키를 생성(또는 열어서) values를 SetValueEx로 기록."""
    with winreg.CreateKey(base, key_path) as key:
        for name, data in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, data)


def install() -> None:
    """이미지→PDF 변환 및 PDF 병합 우클릭 메뉴를 HKCU에 등록."""
    exe = _get_exe_path()
    hkcu = winreg.HKEY_CURRENT_USER

    # 이미지 확장자별 convert 등록
    for ext in (".jpg", ".jpeg", ".png", ".bmp"):
        shell_key = rf"Software\Classes\SystemFileAssociations\{ext}\shell\pdf_maker_convert"
        cmd_key = shell_key + r"\command"

        _set_key(hkcu, shell_key, {
            "MUIVerb": "이미지 → PDF 변환",
            "MultiSelectModel": "Player",
        })
        _set_key(hkcu, cmd_key, {
            "": f'"{exe}" convert "%1"',
        })

    # 모든 파일 대상 merge 등록
    shell_key = r"Software\Classes\*\shell\pdf_maker_merge"
    cmd_key = shell_key + r"\command"

    _set_key(hkcu, shell_key, {
        "MUIVerb": "PDF로 병합",
        "MultiSelectModel": "Player",
    })
    _set_key(hkcu, cmd_key, {
        "": f'"{exe}" merge "%1"',
    })


def _delete_key_tree(base: int, key_path: str) -> None:
    """key_path 아래 하위 키를 모두 재귀 삭제 후 자신도 삭제. 키 없으면 무시."""
    try:
        with winreg.OpenKey(base, key_path, access=winreg.KEY_ALL_ACCESS) as key:
            # 하위 키 목록 수집 후 재귀 삭제
            subkeys = []
            i = 0
            while True:
                try:
                    subkeys.append(winreg.EnumKey(key, i))
                    i += 1
                except OSError:
                    break
        for sub in subkeys:
            _delete_key_tree(base, key_path + "\\" + sub)
        winreg.DeleteKey(base, key_path)
    except FileNotFoundError:
        pass  # 키 없으면 무시


def uninstall() -> None:
    """install()이 등록한 레지스트리 키를 모두 삭제."""
    hkcu = winreg.HKEY_CURRENT_USER

    for ext in (".jpg", ".jpeg", ".png", ".bmp"):
        _delete_key_tree(
            hkcu,
            rf"Software\Classes\SystemFileAssociations\{ext}\shell\pdf_maker_convert",
        )

    _delete_key_tree(
        hkcu,
        r"Software\Classes\*\shell\pdf_maker_merge",
    )
