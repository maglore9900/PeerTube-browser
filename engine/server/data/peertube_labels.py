"""PeerTube default video category and language labels.

Responsibilities:
- Map PeerTube's stock category ids and language codes to display labels for /api/video.
- Leave unknown ids and codes raw.
"""

from __future__ import annotations

# rat-tail: stock PeerTube lists only, so plugin-added or renamed categories and languages show their raw id or code; upgrade path is fetching and caching each instance's /api/v1/videos/categories and /api/v1/videos/languages.
CATEGORY_LABELS: dict[str, str] = {"1": "Music", "2": "Films", "3": "Vehicles", "4": "Art", "5": "Sports", "6": "Travels", "7": "Gaming", "8": "People", "9": "Comedy", "10": "Entertainment", "11": "News & Politics", "12": "How To", "13": "Education", "14": "Activism", "15": "Science & Technology", "16": "Animals", "17": "Kids", "18": "Food"}

# Verbatim body of a stock instance's GET /api/v1/videos/languages; kept on one line so it stays diffable against that response.
LANGUAGE_LABELS: dict[str, str] = {"aa":"Afar","ab":"Abkhazian","af":"Afrikaans","ak":"Akan","am":"Amharic","ar":"Arabic","an":"Aragonese","ase":"American Sign Language","as":"Assamese","asq":"Austrian Sign Language","av":"Avaric","avk":"Kotava","ay":"Aymara","az":"Azerbaijani","ba":"Bashkir","bm":"Bambara","be":"Belarusian","bn":"Bengali","bfi":"British Sign Language","bi":"Bislama","bo":"Tibetan","bs":"Bosnian","br":"Breton","bg":"Bulgarian","bzs":"Brazilian Sign Language","ca":"Catalan","cs":"Czech","ch":"Chamorro","ce":"Chechen","cv":"Chuvash","kw":"Cornish","co":"Corsican","cr":"Cree","cse":"Czech Sign Language","csl":"Chinese Sign Language","cy":"Welsh","da":"Danish","de":"German","dv":"Dhivehi","dsl":"Danish Sign Language","dz":"Dzongkha","el":"Greek","en":"English","eo":"Esperanto","et":"Estonian","eu":"Basque","ee":"Ewe","fo":"Faroese","fa":"Persian","fj":"Fijian","fi":"Finnish","fr":"French","fy":"Western Frisian","fse":"Finnish Sign Language","fsl":"French Sign Language","ff":"Fulah","gcf":"Guadeloupean Creole French","gd":"Scottish Gaelic","ga":"Irish","gl":"Galician","gv":"Manx","gn":"Guarani","gsg":"German Sign Language","gsw":"Swiss German","gu":"Gujarati","ht":"Haitian","ha":"Hausa","sh":"Serbo-Croatian","he":"Hebrew","hz":"Herero","hi":"Hindi","ho":"Hiri Motu","hr":"Croatian","hu":"Hungarian","hy":"Armenian","ig":"Igbo","ii":"Sichuan Yi","iu":"Inuktitut","id":"Indonesian","ik":"Inupiaq","is":"Icelandic","it":"Italian","jv":"Javanese","jbo":"Lojban","ja":"Japanese","jsl":"Japanese Sign Language","kab":"Kabyle","kl":"Kalaallisut","kn":"Kannada","ks":"Kashmiri","ka":"Georgian","kr":"Kanuri","kk":"Kazakh","km":"Khmer","ki":"Kikuyu","rw":"Kinyarwanda","ky":"Kirghiz","kv":"Komi","kg":"Kongo","ko":"Korean","kj":"Kuanyama","ku":"Kurdish","lo":"Lao","la":"Latin","lv":"Latvian","li":"Limburgan","ln":"Lingala","lt":"Lithuanian","lb":"Luxembourgish","lu":"Luba-Katanga","lg":"Ganda","mh":"Marshallese","ml":"Malayalam","mr":"Marathi","mk":"Macedonian","mg":"Malagasy","mt":"Maltese","mn":"Mongolian","mi":"Maori","ms":"Malay (macrolanguage)","my":"Burmese","na":"Nauru","nv":"Navajo","nr":"South Ndebele","nd":"North Ndebele","ng":"Ndonga","ne":"Nepali (macrolanguage)","nl":"Dutch","nn":"Norwegian Nynorsk","nb":"Norwegian Bokmål","no":"Norwegian","ny":"Nyanja","oc":"Occitan","oj":"Ojibwa","or":"Oriya (macrolanguage)","om":"Oromo","os":"Ossetian","pa":"Panjabi","pks":"Pakistan Sign Language","pl":"Polish","pt":"Portuguese (Brazilian)","ps":"Pushto","qu":"Quechua","rm":"Romansh","ro":"Romanian","rsl":"Russian Sign Language","rn":"Rundi","ru":"Russian","sg":"Sango","sdl":"Saudi Arabian Sign Language","sfs":"South African Sign Language","si":"Sinhala","sk":"Slovak","sl":"Slovenian","se":"Northern Sami","sm":"Samoan","sn":"Shona","sd":"Sindhi","so":"Somali","st":"Southern Sotho","es":"Spanish (Spain)","sq":"Albanian","sc":"Sardinian","sr":"Serbian","ss":"Swati","su":"Sundanese","sw":"Swahili (macrolanguage)","sv":"Swedish","swl":"Swedish Sign Language","ty":"Tahitian","ta":"Tamil","tt":"Tatar","te":"Telugu","tg":"Tajik","tl":"Tagalog","th":"Thai","ti":"Tigrinya","tlh":"Klingon","to":"Tonga (Tonga Islands)","tn":"Tswana","ts":"Tsonga","tk":"Turkmen","tr":"Turkish","tw":"Twi","ug":"Uighur","uk":"Ukrainian","ur":"Urdu","uz":"Uzbek","ve":"Venda","vi":"Vietnamese","wa":"Walloon","wo":"Wolof","xh":"Xhosa","yi":"Yiddish","yo":"Yoruba","za":"Zhuang","zh":"Chinese","zu":"Zulu","zxx":"No linguistic content","tok":"Toki Pona","pt-PT":"Portuguese (Portugal)","es-419":"Spanish (Latin America)","zh-Hans":"Simplified Chinese","zh-Hant":"Traditional Chinese","ca-valencia":"Valencian","rcf":"Réunion Creole French","gcr":"Guianese Creole French"}


def category_label(value: str | None) -> str:
    """Return the display label for a stored category: a digit-only id resolves through the default map, anything else (or an unknown id) is returned as is; "" when empty."""
    if not isinstance(value, str) or not value:
        return ""
    # isascii keeps Unicode digits such as "١٥" out of the id lookup.
    if value.isascii() and value.isdigit():
        return CATEGORY_LABELS.get(value, value)
    return value


def language_label(value: str | None) -> str:
    """Return the display label for a stored language code (case-sensitive, e.g. "zh-Hans"); an unknown code is returned raw; "" when empty."""
    if not isinstance(value, str) or not value:
        return ""
    return LANGUAGE_LABELS.get(value, value)
