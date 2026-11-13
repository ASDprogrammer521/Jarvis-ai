from __future__ import annotations
import builtins
import sys
_PREFIXES=("✅","❌","⚠️","✨","🤖","🔔","📱","🌐","⚙️","🔒","🧹","🟢","🔴","⏳")
def style_terminal_text(message):
    text=str(message); trimmed=text.lstrip()
    if not trimmed or any(trimmed.startswith(p) for p in _PREFIXES):return text
    lowered=trimmed.lower()
    if any(w in lowered for w in ("traceback","exception","error","failed","failure","unauthorized","offline","not connected","disconnected","not linked","no phone","refused","timeout")):prefix="❌"
    elif any(w in lowered for w in ("warning","warn:","deprecated","retrying")):prefix="⚠️"
    elif any(w in lowered for w in ("connected","ready","success","completed","complete","saved","started","online","listening")):prefix="✅"
    else:prefix="✨"
    return f"{text[:len(text)-len(trimmed)]}{prefix} {trimmed}"
def install_terminal_styling():
    original=builtins.print
    if getattr(original,"_jarvis_terminal_styled",False):return
    def styled_print(*args,**kwargs):
        if set(kwargs)-{"sep","end","file","flush"}:return original(*args,**kwargs)
        sep=kwargs.get("sep"," ");end=kwargs.get("end","\n");file=kwargs.get("file",None);stream=sys.stdout if file is None else file
        if not args or stream not in (sys.stdout,sys.stderr) or end not in (None,"\n") or (sep is not None and not isinstance(sep,str)):
            return original(*args,**kwargs)
        message=(" " if sep is None else sep).join(str(arg) for arg in args)
        try:return original(style_terminal_text(message),end=end,file=file,flush=kwargs.get("flush",False))
        except UnicodeEncodeError:return original(*args,**kwargs)
    styled_print._jarvis_terminal_styled=True;styled_print._jarvis_original_print=original;builtins.print=styled_print

#by ASDcuber
