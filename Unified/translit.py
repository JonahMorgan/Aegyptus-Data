"""Normalization keys used to match lemmas across sources.

Egyptian/Demotic transliteration differs per source:
  TLA corpus   ꞽw, šmi̯, ḥr.ꞽ-rḫt     (ꞽ / i̯ for yod, dots for morph boundaries)
  ORAEC        jri̯, ꜥq.y
  Wiktionary   jrj, jpꜣt               (j, no dots)
  DME (MdC)    iAw, rmT, Sna           (ASCII Manuel de Codage, case-sensitive)
  TLA Demotic  ḥwṱ, tꜣy=               (ṱ for ṯ)
egy_key() folds all of these onto one form; egy_loose_key() additionally folds
distinctions that sources disagree on (z/s, y/j).
"""
import re
import unicodedata

_COPTIC_STRIP = re.compile(r"[\-⸗=()\[\]\s.·ʼ'`]")


def coptic_key(s):
    """Coptic form -> match key: drop combining marks (supralinear strokes etc.), hyphens, morph boundaries."""
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _COPTIC_STRIP.sub("", s)


# Manuel de Codage -> Unicode transliteration (case-sensitive, so applied before lowercasing).
_MDC = {
    "A": "ꜣ", "i": "j", "a": "ꜥ", "H": "ḥ", "x": "ḫ", "X": "ẖ",
    "S": "š", "T": "ṯ", "D": "ḏ", "q": "q", "Q": "q",
}


def mdc_to_unicode(s):
    return "".join(_MDC.get(c, c) for c in s or "")


_EGY_REPLACE = [
    ("i̯", "j"),  # i̯ (weak yod)
    ("ı͗", "j"), ("i͗", "j"),  # ı͗ / i͗
    ("ꞽ", "j"), ("Ꞽ", "j"), ("ỉ", "j"), ("ı", "j"), ("i", "j"),
    ("ʿ", "ꜥ"), ("ʾ", "ꜣ"), ("ṱ", "ṯ"), ("ḳ", "q"),  # ḳ: older notation for q
]
_EGY_STRIP = re.compile(r"[\s.\-=⸗()\[\]⟨⟩{}〈〉<>'\"~*?!/\\,;:0-9_|]")


def egy_key(s):
    """Egyptian or Demotic transliteration (Unicode) -> match key."""
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s).lower()
    for a, b in _EGY_REPLACE:
        s = s.replace(a, b)
    s = unicodedata.normalize("NFD", s)
    # keep the underdots/breves that distinguish letters (ḥ ḫ ẖ š ṯ ḏ), drop everything else combining
    keep = {"̣", "̮", "̱", "̌"}
    s = "".join(c for c in s if not unicodedata.combining(c) or c in keep)
    s = unicodedata.normalize("NFC", s)
    return _EGY_STRIP.sub("", s)


def egy_loose_key(s):
    return egy_key(s).replace("z", "s").replace("y", "j")


def egy_key_from_mdc(s):
    return egy_key(mdc_to_unicode(s))
