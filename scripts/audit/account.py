#!/usr/bin/env python3
"""Shop-URL zu Kundenordner auflösen (Spec Abschnitt 5.0).

Jeder Lauf beginnt mit dieser Frage: zu welchem Kunden gehört diese Domain? Die
Antwort steht in der `domains:`-Zeile im Frontmatter der `entity.md` unter
`<PTAI_ACCOUNTS_ROOT>/<slug>/`. Vier Ausgänge, mehr gibt es nicht: `exact`,
`subdomain`, `ambiguous`, `none`. Der Aufrufer entscheidet, was daraus folgt.
`create()` legt einen fehlenden Kunden an, aber nie über einen vorhandenen Ordner.

Wo die Kundenordner liegen, sagt die Einstellung, nicht das Plugin. Bis
11.09.2026 stand hier eine feste Vorgabe mit einem Pfad in Yves' Drive, und bei
jedem anderen Betreiber fand `resolve()` still keinen einzigen Kunden
(Spec 2026-09-11 public release, A1).

Die Vorlage ist `resolveAccount()` aus dem alten Repo (`engine/archive-screens.mjs`).
Ein Unterschied ist beabsichtigt und wichtig: die alte Funktion liest nur die
`domains:`-Zeile selbst und kennt damit die Inline-Form und die Klammerform. Fünf
Accounts pflegen ihre Domain aber als YAML-Blockliste in den Folgezeilen, und für
die lieferte sie ein leeres Ergebnis, obwohl die Domain sauber gepflegt war. Wer
das in den Daten "repariert", schreibt einen Inline-Wert neben eine stehen
gebliebene Blockliste und hinterlässt zwei Wahrheiten. Deshalb liest dieses Modul
alle drei Schreibweisen.

CLI:
  python3 -m audit.account <shop-url> [--accounts=<pfad>]       auflösen, legt nichts an
  python3 -m audit.account create <shop-url> [--brand=<marke>]  auflösen, sonst anlegen

Exit-Codes: 0 Kunde gefunden oder angelegt, 1 Aufruf falsch, 2 kein eindeutiger
Kunde, 3 Kundenordner belegt, 4 PTAI_ACCOUNTS_ROOT unbrauchbar.
"""
import http.client
import os
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from audit import env

#: Die Einstellung für den Ordner, der die Kundenordner enthält.
ROOT_SETTING = "PTAI_ACCOUNTS_ROOT"

#: Gilt, wenn die Einstellung nirgends steht. Die Tilde löst `accounts_root()` auf.
DEFAULT_ROOT = "~/ptai-ecom/accounts"


class AccountsRootError(RuntimeError):
    """Die Einstellung zeigt auf keinen brauchbaren Ordner."""


def accounts_root(workspace: str | os.PathLike = ".") -> str:
    """Der Ordner mit den Kundenordnern, absolut und mit aufgelöster Tilde.

    Gesucht wie jeder Wert des Betreibers über `audit.env`: Umgebung, `.env` im
    Workspace, zentrale Datei. Steht die Einstellung nirgends, gilt
    `DEFAULT_ROOT`, und die darf fehlen: vor dem ersten Kunden gibt es sie nicht.

    **Eine gesetzte Einstellung ohne Ordner ist ein Fehler, kein leeres
    Ergebnis.** Liegt die Wurzel in einem Cloud-Ordner, der gerade nicht
    eingebunden ist, fände `resolve()` sonst keinen Kunden, und audit-light legte
    einen zweiten an. Ein relativer Wert ist aus demselben Grund ein Fehler: der
    Ort hinge davon ab, aus welchem Verzeichnis ein Lauf startet.
    """
    value = env.get(ROOT_SETTING, workspace)
    if not value:
        return os.path.normpath(os.path.expanduser(DEFAULT_ROOT))
    path = os.path.normpath(os.path.expanduser(value))
    if not os.path.isabs(path):
        raise AccountsRootError(
            f"{ROOT_SETTING}={value!r} ist kein absoluter Pfad. Einen vollen Pfad "
            f"oder einen mit ~ eintragen.")
    if not os.path.isdir(path):
        raise AccountsRootError(
            f"{ROOT_SETTING} zeigt auf {path}, den Ordner gibt es nicht. Liegt er in "
            f"einem Cloud-Ordner, prüfen, ob der eingebunden ist.")
    return path

#: Frontmatter-Zeile, ab der gelesen wird. Der Rest der Datei wird nie angefasst.
_DOMAINS_LINE = re.compile(r"^domains:[ \t]*(.*)$", re.M)
_LIST_ITEM = re.compile(r"^\s*-\s+(.+?)\s*$")


def normalize_host(value: str) -> str:
    """Reduziert eine URL oder Domain auf den vergleichbaren Host.

    Schema, Pfad, Port, führendes `www.` und Groß-/Kleinschreibung fallen weg.
    Leere oder unbrauchbare Eingaben ergeben einen leeren String, nie None: der
    Aufrufer prüft dann auf falsy und muss keinen zweiten Typ behandeln.
    """
    if not value:
        return ""
    v = str(value).strip().strip("\"'").lower()
    v = re.sub(r"^[a-z][a-z0-9+.-]*://", "", v)
    v = v.split("/")[0].split("?")[0].split("#")[0]
    v = v.split("@")[-1]          # falls jemand eine Mailadresse übergibt
    v = v.split(":")[0]           # Port
    if v.startswith("www."):
        v = v[4:]
    return v.strip(".")


def parse_domains(text: str) -> list[str]:
    """Liest alle Domains aus dem Frontmatter, in allen drei Schreibweisen.

    Inline (`domains: a.de, b.de`), Klammer (`domains: [a.de, b.de]`) und
    YAML-Blockliste (`domains:` mit `  - a.de` in den Folgezeilen). Bei der
    Blockliste endet das Lesen an der ersten Zeile, die kein Listenpunkt ist,
    damit das nächste Frontmatter-Feld nicht als Domain durchgeht.
    """
    m = _DOMAINS_LINE.search(text or "")
    if not m:
        return []

    inline = m.group(1).strip()
    if inline:
        inline = inline.strip("[]")
        return [h for h in (normalize_host(p) for p in inline.split(",")) if h]

    out: list[str] = []
    for line in text[m.end():].splitlines()[1:]:
        if not line.strip():
            continue
        item = _LIST_ITEM.match(line)
        if not item:
            break
        host = normalize_host(item.group(1))
        if host:
            out.append(host)
    return out


def _split_inline(value: str) -> list[str]:
    """Trennt eine Inline-Liste an Kommas außerhalb von Anführungszeichen.

    Ein Anführungszeichen öffnet nur am Anfang eines Eintrags. Mitten im Wort
    ist es ein Apostroph, `O'Beispiel` bleibt ein Name.
    """
    parts, current, quote = [], "", None
    for char in value:
        if quote:
            if char == quote:
                quote = None
            else:
                current += char
        elif char in "\"'" and not current.strip():
            quote, current = char, ""
        elif char == ",":
            parts.append(current.strip())
            current = ""
        else:
            current += char
    parts.append(current.strip())
    return [part for part in parts if part]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1].strip()
    return value


def parse_list(text: str, field: str) -> list[str]:
    """Die Einträge eines Listenfelds im Frontmatter, roh und ohne Normalisierung.

    Dieselben drei Schreibweisen wie `parse_domains()`: Inline, Klammer und
    YAML-Blockliste. Anführungszeichen werden respektiert, ein Komma darin
    trennt nichts.
    """
    m = re.search(rf"^{re.escape(field)}:[ \t]*(.*)$", text or "", re.M)
    if not m:
        return []
    inline = m.group(1).strip()
    if inline:
        if inline.startswith("[") and inline.endswith("]"):
            inline = inline[1:-1]
        return _split_inline(inline)
    out: list[str] = []
    for line in text[m.end():].splitlines()[1:]:
        if not line.strip():
            continue
        item = _LIST_ITEM.match(line)
        if not item:
            break
        value = _unquote(item.group(1))
        if value:
            out.append(value)
    return out


def parse_aliases(text: str) -> list[str]:
    """Andere Schreibweisen von Marke und Firma aus `aliases:`.

    Ohne `normalize_host()`: ein Alias ist ein Name, und die Leak-Prüfung sucht
    ihn so, wie er dasteht (Spec 2026-09-11 public release, C2).
    """
    return parse_list(text, "aliases")


def load_accounts(accounts_dir: str | None = None) -> dict[str, list[str]]:
    """Alle Kunden mit ihren Domains. Ein Ordner ohne `entity.md` zählt nicht.

    Ein ausdrücklich übergebener Ordner, den es nicht gibt, ergibt ein leeres
    Ergebnis. Ohne Argument gilt `accounts_root()`, und das wirft bei einer
    gesetzten Einstellung ohne Ordner.
    """
    root = accounts_dir or accounts_root()
    found: dict[str, list[str]] = {}
    if not os.path.isdir(root):
        return found
    for slug in sorted(os.listdir(root)):
        entity = os.path.join(root, slug, "entity.md")
        if not os.path.isfile(entity):
            continue
        with open(entity, encoding="utf-8", errors="replace") as fh:
            found[slug] = parse_domains(fh.read())
    return found


def resolve(shop_url: str, accounts_dir: str | None = None) -> dict:
    """Ordnet eine Shop-URL einem Account zu.

    Ergebnis: `{"status", "slug", "host", "candidates"}`. `status` ist einer von
    `exact`, `subdomain`, `ambiguous`, `none`. `slug` ist nur bei `exact` und
    `subdomain` gesetzt, bei `ambiguous` stehen die Treffer in `candidates`.

    Ein exakter Treffer schlägt einen Subdomain-Treffer: trägt ein Account
    `shop.example.de` und ein anderer `example.de`, gewinnt der erste für
    `shop.example.de`. Sonst würde eine Holding jeden ihrer Shops einsammeln.
    """
    host = normalize_host(shop_url)
    if not host:
        return {"status": "none", "slug": None, "host": "", "candidates": []}

    accounts = load_accounts(accounts_dir)
    exact, partial = [], []
    for slug, domains in accounts.items():
        for d in domains:
            if d == host:
                exact.append(slug)
                break
            if host.endswith("." + d) or d.endswith("." + host):
                partial.append(slug)
                break

    hits, status = (exact, "exact") if exact else (partial, "subdomain")
    hits = sorted(set(hits))
    if len(hits) == 1:
        return {"status": status, "slug": hits[0], "host": host, "candidates": hits}
    if len(hits) > 1:
        return {"status": "ambiguous", "slug": None, "host": host, "candidates": hits}
    return {"status": "none", "slug": None, "host": host, "candidates": []}


def account_path(slug: str) -> str:
    """Absoluter Pfad zum Kundenordner, `<PTAI_ACCOUNTS_ROOT>/<slug>`."""
    return os.path.join(accounts_root(), slug)


def drive_path(slug: str) -> str:
    """Der `drive_path` für `reporting/config.json` und die Lauf-Config von audit-light.

    Absolut, weil `check_env.sh` und `config.validate()` einen relativen Wert
    ablehnen: er landete relativ zum Workspace, also im Kunden-Repo. Der Name
    stammt aus Stufe 1; der Ordner muss kein Drive sein.
    """
    return account_path(slug)


#: Zweiteilige Endungen, vor denen der Slug ein Label weiter links steht.
#: Bewusst eine kurze feste Liste statt der Public-Suffix-Liste: die bräuchte
#: eine Abhängigkeit oder eine Datei, die niemand pflegt, und ein Slug, der
#: einmal danebenliegt, lässt sich beim Anlegen von Hand korrigieren.
TWO_PART_ENDINGS = ("co.uk", "com.au", "co.at", "or.at")

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slug_from_host(host: str) -> str:
    """Der Name eines neuen Kundenordners, abgeleitet aus dem Host.

    `www.`, Schema, Pfad und Subdomains fallen weg, übrig bleibt das Label vor
    der Endung in kebab-case: `shop.beispiel-shop.de` wird `beispiel-shop`. Bei
    einer Endung aus `TWO_PART_ENDINGS` zählt das Label davor. Leere Eingabe
    ergibt einen leeren String.
    """
    labels = [label for label in normalize_host(host).split(".") if label]
    if not labels:
        return ""
    if len(labels) >= 3 and ".".join(labels[-2:]) in TWO_PART_ENDINGS:
        label = labels[-3]
    elif len(labels) >= 2:
        label = labels[-2]
    else:
        label = labels[0]
    return re.sub(r"[^a-z0-9]+", "-", label.translate(_UMLAUTS)).strip("-")


class AccountExistsError(FileExistsError):
    """Der Kundenordner existiert schon; es wurde nichts geschrieben."""


def _exists_error(root: str, slug: str, host: str) -> AccountExistsError:
    folder = os.path.join(root, slug)
    return AccountExistsError(
        f"Kundenordner {folder} existiert schon. Zwei Wege, beide von Hand: "
        f"gehört {host} zu diesem Kunden, {host} in domains: von {folder}/entity.md "
        f"eintragen, in der Listenform, die die Datei schon nutzt. Ist es ein "
        f"eigener Kunde, {os.path.join(root, slug + '-2')}/entity.md mit "
        f"domains: {host} anlegen. Danach den Lauf neu starten.")


def create(slug: str, brand: str, host: str) -> str:
    """Legt `<root>/<slug>/entity.md` an und gibt den Kundenordner zurück.

    Die Datei trägt nur, was `resolve()` und `brand_of()` lesen: `domains:` im
    Frontmatter und die Marke als Überschrift. Mehr weiß ein Lauf über einen
    kalten Lead nicht; alles Weitere ergänzt der Betreiber.

    **Existiert der Ordner schon, schreibt diese Funktion nichts**, auch wenn
    darin keine `entity.md` liegt. Zwei Shops mit demselben Label vor der Endung
    sind ein Kunde mit zwei Domains oder zwei Kunden, und das entscheidet kein
    Muster. `AccountExistsError` nennt beide Wege; ein Lauf bricht damit ab wie
    bei `ambiguous`, ohne Frage (Spec 2026-09-11 public release, A1).
    """
    host = normalize_host(host)
    if not _SLUG.match(slug or ""):
        raise ValueError(f"unbrauchbarer Slug {slug!r}: nur a-z, 0-9 und einzelne Bindestriche")
    if not host:
        raise ValueError("ohne Host findet resolve() den Kunden später nicht wieder")
    root = accounts_root()
    folder = os.path.join(root, slug)
    if os.path.lexists(folder):
        raise _exists_error(root, slug, host)
    name = " ".join(str(brand or "").split()) or slug
    os.makedirs(folder)
    with open(os.path.join(folder, "entity.md"), "x", encoding="utf-8") as fh:
        fh.write(f"---\ndomains: {host}\n---\n\n# {name}\n")
    return folder


def brand_of(slug: str) -> str:
    """Der Markenname aus der `entity.md`, nicht der Firmenname.

    Der Wert landet als `brand` in der Lauf-Config und bestimmt, wonach
    `check-geo` in den AI-Antworten sucht. Deshalb zählt hier die Marke und nicht
    die Rechtsperson: nach "A. Muster & B. Muster GbR" fragt
    niemand eine KI, nach "BEISPIELMARKE" schon.

    Die Überschriften folgen dem Muster `Firmenname (Marke)`, sobald sich beide
    unterscheiden. Steht ein Klammerzusatz da, ist er die Marke; ein führendes
    "Marke " darin fällt weg. Steht keiner da, sind Firma und Marke dasselbe und
    nur die Rechtsform fällt weg. Der Stadium-Zusatz `(Lead)` ist keine Marke.
    """
    entity = os.path.join(account_path(slug), "entity.md")
    if os.path.isfile(entity):
        with open(entity, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.startswith("# "):
                    continue
                title = re.sub(r"\s*\((?:Lead|Kunde|Partner|Prospect)\)\s*$", "",
                               line[2:].strip()).strip()
                klammer = re.search(r"\(([^)]+)\)\s*$", title)
                if klammer:
                    return re.sub(r"^Marke\s+", "", klammer.group(1).strip()).strip()
                return re.sub(r"\s+(GmbH(?:\s*&\s*Co\.\s*KG)?|AG|UG(?:\s*\(haftungsbeschränkt\))?"
                              r"|KG|OHG|GbR|e\.K\.|e\.V\.|Ltd\.?|Inc\.?)\s*$", "", title,
                              flags=re.I).strip() or title
    return slug


def legal_name_of(slug: str) -> str:
    """Die Rechtsperson aus der Überschrift, also alles vor dem Klammerzusatz."""
    entity = os.path.join(account_path(slug), "entity.md")
    if os.path.isfile(entity):
        with open(entity, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("# "):
                    title = re.sub(r"\s*\((?:Lead|Kunde|Partner|Prospect)\)\s*$", "",
                                   line[2:].strip()).strip()
                    return re.sub(r"\s*\([^)]+\)\s*$", "", title).strip()
    return slug


#: Dieselbe Browser-Kennung wie die curl-Aufrufe in audit-light. Mit der Kennung
#: eines Skripts liefern manche Shops eine Bot-Seite ohne Titel.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

#: Trennzeichen im `<title>`, vor denen der Markenname steht. Bindestrich und
#: Gedankenstriche zählen nur mit Leerzeichen auf beiden Seiten, sonst zerfiele
#: `Beispiel-Shop`. Die Gedankenstriche stehen als `chr()`, weil der Quelltext
#: sie nicht als Zeichen trägt.
_SEPARATORS = "|" + chr(0xB7) + chr(0x2022)
_DASHES = "-" + chr(0x2013) + chr(0x2014)
_TITLE_SPLIT = re.compile(r"\s*[" + re.escape(_SEPARATORS) + r"]\s*"
                          + r"|\s+[" + re.escape(_DASHES) + r"]\s+|:\s+")


class _HeadParser(HTMLParser):
    """Liest `og:site_name` und den ersten `<title>`, sonst nichts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.site_name = None
        self.title = None
        self._title_parts = None

    def handle_starttag(self, tag, attrs):
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta" and self.site_name is None:
            if "og:site_name" in (values.get("property", "").lower(),
                                  values.get("name", "").lower()):
                self.site_name = values.get("content", "")
        elif tag == "title" and self.title is None and self._title_parts is None:
            self._title_parts = []

    def handle_data(self, data):
        if self._title_parts is not None:
            self._title_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "title" and self._title_parts is not None:
            self.title = "".join(self._title_parts)
            self._title_parts = None


def homepage_brand(page: str | None) -> tuple[str, str] | None:
    """Der Markenname aus dem Quelltext einer Startseite, mit seiner Herkunft.

    Zuerst `og:site_name`, den ein Shop ausdrücklich als seinen Namen setzt,
    sonst der erste Teil des `<title>`. None, wenn beides fehlt oder leer ist.
    """
    parser = _HeadParser()
    parser.feed(page or "")
    parser.close()
    site_name = " ".join((parser.site_name or "").split())
    if site_name:
        return site_name, "og:site_name"
    title = " ".join((parser.title or "").split())
    first = next((part.strip() for part in _TITLE_SPLIT.split(title) if part.strip()), "")
    return (first, "title") if first else None


def fetch_homepage(url: str, timeout: float = 25) -> str | None:
    """Ein Abruf einer Seite, höchstens ein Megabyte. Jeder Fehler ergibt None."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read(2 ** 20).decode(charset, errors="replace")
    except (OSError, ValueError, LookupError, http.client.HTTPException):
        return None


def _homepage_url(shop_url: str) -> str:
    """Die Startseite zur Shop-URL, mit `https://`, falls das Schema fehlt."""
    raw = str(shop_url or "").strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    parts = urllib.parse.urlsplit(raw)
    return f"{parts.scheme}://{parts.netloc}/"


def find_or_create(shop_url: str, brand: str | None = None, fetch=fetch_homepage) -> dict:
    """Den Kunden zur Shop-URL finden oder anlegen (Spec 2026-09-11 public release, A1, A2).

    Ergebnis wie `resolve()`, dazu `created`, `brand`, `brand_source` und
    `drive_path`. `status` ist `exact`, `subdomain`, `ambiguous`, `created`, oder
    `none` bei leerer URL. Bei `ambiguous` entsteht nichts.

    Die Marke kommt in dieser Reihenfolge: `brand`, dann bei einem vorhandenen
    Kunden die Überschrift seiner `entity.md` (`brand_of()`, danach sucht
    `check-geo`), dann für einen neuen Kunden die Startseite, sonst der Slug.
    Die Startseite wird genau einmal abgerufen, und erst, wenn feststeht, dass
    der Ordner frei ist.

    Wirft `AccountExistsError`, wenn der Ordner für den Slug schon existiert,
    und `AccountsRootError` bei einer unbrauchbaren Wurzel.
    """
    found = resolve(shop_url)
    result = {**found, "created": False, "brand": None, "brand_source": None,
              "drive_path": None}
    if found["slug"]:
        return {**result, "brand": brand or brand_of(found["slug"]),
                "brand_source": "argument" if brand else "entity.md",
                "drive_path": drive_path(found["slug"])}
    if found["status"] != "none" or not found["host"]:
        return result
    slug = slug_from_host(found["host"])
    root = accounts_root()
    if _SLUG.match(slug) and os.path.lexists(os.path.join(root, slug)):
        raise _exists_error(root, slug, found["host"])
    if brand:
        name, source = brand, "argument"
    else:
        name, source = homepage_brand(fetch(_homepage_url(shop_url))) or (slug, "slug")
    create(slug, name, found["host"])
    return {**result, "status": "created", "slug": slug, "candidates": [slug],
            "created": True, "brand": name, "brand_source": source,
            "drive_path": drive_path(slug)}


if __name__ == "__main__":
    argv = sys.argv[1:]
    creating = bool(argv) and argv[0] == "create"
    if creating:
        argv = argv[1:]
    args = [a for a in argv if not a.startswith("--")]
    option = lambda name: next((a.split("=", 1)[1] for a in argv
                                if a.startswith(f"--{name}=")), None)
    if not args:
        print("Aufruf: python3 -m audit.account <shop-url> [--accounts=<pfad>]\n"
              "        python3 -m audit.account create <shop-url> [--brand=<marke>]",
              file=sys.stderr)
        raise SystemExit(1)
    try:
        if creating:
            result = find_or_create(args[0], brand=option("brand"))
        else:
            result = resolve(args[0], option("accounts"))
        slug = result["slug"]
        brand = (result.get("brand") or brand_of(slug)) if slug else None
        path = drive_path(slug) if slug else None
    except AccountExistsError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(3)
    except AccountsRootError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(4)
    print(f"host:       {result['host']}")
    print(f"status:     {result['status']}")
    print(f"slug:       {slug or '-'}")
    if result["candidates"] and not slug:
        print(f"kandidaten: {', '.join(result['candidates'])}")
    if slug:
        print(f"brand:      {brand}")
        if result.get("brand_source"):
            print(f"marke aus:  {result['brand_source']}")
        print(f"drive_path: {path}")
    raise SystemExit(0 if slug else 2)
