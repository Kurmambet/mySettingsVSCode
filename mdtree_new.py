#!/usr/bin/env python3
# Windows: интерактивный режим работает через msvcrt, без windows-curses.
# Linux/macOS: интерактивный режим использует curses.


# Запуск: uv run mdtree.py [--clean | --no-redact | -i]
# Запуск: python3 mdtree.py  (или python3 mdtree.py -i)

# uv run mdtree.py --no-redact              # вообще не искать секреты
# uv run mdtree.py --no-redact-keywords     # выключить только keyword-поиск
# uv run mdtree.py --no-redact-format       # выключить только format-regex
# uv run mdtree.py --clean                  # убрать пробелы, комментарии
# до 50-100K токенов. если проект вырастет за 150-200K, стоит подавать частями через интерактивный режим


# ↑/↓ или j/k — перемещение;
# → / Enter — раскрыть каталог;
# ← / Backspace — свернуть / перейти к родителю;
# Space — выбрать файл или каталог рекурсивно;
# F — сформировать Markdown;
# Q — отмена.


import argparse
import json
import os
import re
import shutil
import sys

if os.name == "nt":
    import msvcrt
else:
    import curses

try:
    import pathspec

    HAS_PATHSPEC = True
except ImportError:
    HAS_PATHSPEC = False

try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text):
        return len(_ENC.encode(text))

    TOKEN_MODE = "tiktoken (cl100k_base, точно для GPT-4/4o/3.5)"
except ImportError:

    def count_tokens(text):
        return max(1, len(text) // 4)

    TOKEN_MODE = "оценка (символы/4, приблизительно)"

CONFIG_FILE = "mdtree_config.json"
PROFILES_FILE = "mdtree_profiles.json"
OUTPUT_FILE = "project_structure.md"
TREE_BRANCH = "├── "
TREE_LAST = "└── "
TREE_VERT = "│   "
TREE_SPACE = "    "
COMMENT_PREFIXES = ("#", "//", "/*")
TYPED_LANG_COLON_EXEMPT = {
    ".py",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".kt",
    ".swift",
    ".c",
    ".cpp",
    ".cs",
    ".h",
    ".hpp",
}
HASH_COMMENT_EXTS = (".py", ".yml", ".yaml", ".toml")
BLOCK_COMMENT_EXTS = (".js", ".ts", ".css", ".vue", ".tsx")

DEFAULT_CONFIG = {
    "exclude_dirs": [
        ".ruff_cache",
        ".git",
        ".venv",
        "__pycache__",
        ".idea",
        ".vscode",
        "postgres_dev_data",
        "redis_dev_data",
        "public",
        "node_modules",
        "dist",
        "dev-dist",
    ],
    "skip_content_dirs": [
        "alembic/versions",
        "backend/alembic",
        "node_modules",
        ".vscode",
        "public",
        ".venv",
    ],
    "skip_content_files": [
        ".dockerignore",
        "uv.lock",
        ".gitignore",
        "alembic.ini",
        "README.md",
        "README",
        "notes.txt",
        "project_structure.md",
        "package-lock.json",
        "tsconfig.node.json",
        "tsconfig.json",
        "tsconfig.app.json",
        "tree.py",
        "docker-compose.dev.yml",
        "seed_messages.py",
        "generate_secret.py",
        "pyproject.toml",
        "__init__.py",
        "rate_limiter.py",
        "exceptions.py",
        "useVideoRecorder.ts",
        "useVoiceRecorder.ts",
        "useAuth.ts",
        "player.ts",
        "tailwind.config.ts",
    ],
    "include_extensions": [
        ".py",
        ".conf",
        ".env",
        ".yml",
        ".yaml",
        ".toml",
        ".json",
        ".js",
        ".ts",
        ".vue",
        ".html",
        ".css",
        ".env.example",
        ".dockerignore",
        "Dockerfile",
        ".tsx",
    ],
    "exclude_extensions": [".woff2", ".png", ".jpg", ".jpeg", ".ico", ".svg", ".lock"],
    "secret_keywords": [
        "SECRET",
        "PASSWORD",
        "PASSWD",
        "TOKEN",
        "API_KEY",
        "APIKEY",
        "DATABASE_URL",
        "DB_URL",
        "PRIVATE_KEY",
        "ACCESS_KEY",
        "CREDENTIAL",
        "CLIENT_SECRET",
        "SESSION_KEY",
    ],
    "use_gitignore": True,
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(user_cfg)
        return cfg
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
    return DEFAULT_CONFIG


CFG = load_config()
EXCLUDE_DIRS = set(CFG["exclude_dirs"])
SKIP_CONTENT_DIRS = set(CFG["skip_content_dirs"])
SKIP_CONTENT_FILES = set(CFG["skip_content_files"])
INCLUDE_EXTENSIONS = set(CFG["include_extensions"])
EXCLUDE_EXTENSIONS = set(CFG.get("exclude_extensions", []))
SECRET_KEYWORDS = CFG["secret_keywords"]
USE_GITIGNORE = CFG.get("use_gitignore", True) and HAS_PATHSPEC


def warn(msg):
    print(f"[warn] {msg}", file=sys.stderr)


class GitignoreResolver:
    def __init__(self, root_path="."):
        self.root_path = os.path.abspath(root_path)
        self.specs = []
        if not HAS_PATHSPEC:
            return
        for dirpath, dirnames, filenames in os.walk(self.root_path):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            if ".gitignore" not in filenames:
                continue
            gi_path = os.path.join(dirpath, ".gitignore")
            try:
                with open(gi_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.read().splitlines()
                spec = pathspec.PathSpec.from_lines("gitwildmatch", lines)
                self.specs.append((dirpath, spec))
            except OSError as e:
                warn(f"не удалось прочитать {gi_path}: {e}")

    def is_ignored(self, abs_path):
        if not HAS_PATHSPEC or not self.specs:
            return False
        for base_dir, spec in self.specs:
            if not (abs_path == base_dir or abs_path.startswith(base_dir + os.sep)):
                continue
            rel = os.path.relpath(abs_path, base_dir).replace(os.sep, "/")
            if spec.match_file(rel):
                return True
        return False


GITIGNORE = GitignoreResolver(".") if USE_GITIGNORE else None


def is_gitignored(path):
    return GITIGNORE is not None and GITIGNORE.is_ignored(os.path.abspath(path))


def _split_words(identifier):
    tokens = re.split(r"[^A-Za-z0-9]+", identifier)
    words = []
    for t in tokens:
        if not t:
            continue
        camel = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z0-9]+", t)
        words.extend(camel if camel else [t])
    return [w.upper() for w in words if w]


_KEYWORD_WORD_SEQS = [kw.upper().split("_") for kw in SECRET_KEYWORDS]


def is_secret_identifier(identifier):
    words = _split_words(identifier)
    for seq in _KEYWORD_WORD_SEQS:
        n = len(seq)
        for i in range(len(words) - n + 1):
            if words[i : i + n] == seq:
                return True
    return False


_LINE_KV_RE = re.compile(
    r"^([ \t]*)(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2([ \t]*[:=][ \t]*)(.*)$"
)
_QUOTED_VALUE_RE = re.compile(r"^(['\"])(.*)\1(.*)$")
_BARE_TOKEN_RE = re.compile(r"^(\$\{[^}]*\}|\$\w+|[^\s,;#]+)(.*)$")
_CODE_REF_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[^\]\n]*\])+$"
)


def is_code_reference(token):
    if "." not in token and "[" not in token:
        return False
    return bool(_CODE_REF_RE.match(token))


def _redact_line(line, ext, hits):
    m = _LINE_KV_RE.match(line)
    if not m:
        return line
    indent, quote, identifier, sep, rest = m.groups()
    if not is_secret_identifier(identifier):
        return line
    sep_char = ":" if ":" in sep else "="
    if sep_char == ":" and ext in TYPED_LANG_COLON_EXEMPT:
        return line
    rest_stripped = rest.strip()
    if not rest_stripped or rest_stripped[0] in "[{(":
        return line
    qm = _QUOTED_VALUE_RE.match(rest_stripped)
    if qm:
        q, _, tail = qm.groups()
        hits.append(identifier)
        return f"{indent}{quote}{identifier}{quote}{sep.rstrip()} {q}{q}{tail}"
    if "(" in rest_stripped:
        return line
    tm = _BARE_TOKEN_RE.match(rest_stripped)
    if not tm:
        return line
    token, tail = tm.groups()
    if token.startswith("$") or is_code_reference(token):
        return line
    hits.append(identifier)
    return f"{indent}{quote}{identifier}{quote}{sep.rstrip()}{tail}"


FORMAT_SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS_ACCESS_KEY_REDACTED"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OPENAI_KEY_REDACTED"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "GITHUB_TOKEN_REDACTED"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "SLACK_TOKEN_REDACTED"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "GOOGLE_API_KEY_REDACTED"),
    (
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        "JWT_REDACTED",
    ),
    (
        re.compile(r"(?i)\b\w+://[^:\s\"']+:[^@\s\"']+@[^\s\"']+"),
        "CONNECTION_STRING_REDACTED",
    ),
    (
        re.compile(
            r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----[\s\S]+?-----END (RSA |EC |OPENSSH |)PRIVATE KEY-----"
        ),
        "PRIVATE_KEY_BLOCK_REDACTED",
    ),
]
REDACTION_LOG = {}


def redact_secrets(
    content,
    filename="file.txt",
    filename_for_log=None,
    use_keywords=True,
    use_format_regex=True,
):
    ext = os.path.splitext(filename)[1]
    hits = []
    if use_keywords:
        content = "\n".join(_redact_line(ln, ext, hits) for ln in content.split("\n"))
    if use_format_regex:
        for pattern, placeholder in FORMAT_SECRET_PATTERNS:
            n_before = len(pattern.findall(content))
            if n_before:
                hits.extend([placeholder] * n_before)
            content = pattern.sub(placeholder, content)
    if filename_for_log is not None and hits:
        REDACTION_LOG.setdefault(filename_for_log, []).extend(hits)
    return content


TRIPLE_DQ = '"' * 3
TRIPLE_SQ = "'" * 3


def _is_dockerfile(filename):
    return filename == "Dockerfile" or filename.startswith("Dockerfile.")


def clean_code(content, filename):
    ext = os.path.splitext(filename)[1]
    is_hash_comment = ext in HASH_COMMENT_EXTS or _is_dockerfile(filename)
    is_block_comment = ext in BLOCK_COMMENT_EXTS
    if is_block_comment:
        content = re.sub(r"/\*[\s\S]*?\*/", "", content)
    elif ext == ".py":
        content = re.sub(TRIPLE_DQ + r".*?" + TRIPLE_DQ, "", content, flags=re.DOTALL)
        content = re.sub(TRIPLE_SQ + r".*?" + TRIPLE_SQ, "", content, flags=re.DOTALL)
    cleaned_lines = []
    for i, line in enumerate(content.split("\n")):
        stripped = line.strip()
        if i == 0 and stripped.startswith(COMMENT_PREFIXES):
            cleaned_lines.append(line)
            continue
        if not stripped:
            continue
        if is_block_comment:
            if stripped.startswith("//"):
                continue
            line = re.sub(r"(?<!:)\/\/.*", "", line)
        elif is_hash_comment:
            if stripped.startswith("#"):
                continue
            if " #" in line:
                line = line.split(" #")[0]
        if line.strip():
            cleaned_lines.append(line.rstrip())
    return "\n".join(cleaned_lines)


LANG_MAP = {
    ".py": "python",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".js": "javascript",
    ".ts": "typescript",
    ".vue": "vue",
    ".html": "html",
    ".css": "css",
    ".md": "markdown",
    "Dockerfile": "dockerfile",
    ".tsx": "tsx",
}


def get_lang(filename):
    if _is_dockerfile(filename):
        return "dockerfile"
    for ext, lang in LANG_MAP.items():
        if filename.endswith(ext):
            return lang
    return "text"


def is_valid_ext(filename):
    if filename.endswith(tuple(EXCLUDE_EXTENSIONS)):
        return False
    if _is_dockerfile(filename):
        return "Dockerfile" in INCLUDE_EXTENSIONS
    return filename.endswith(tuple(INCLUDE_EXTENSIONS))


def dir_is_excluded(dirname, full_path):
    return dirname in EXCLUDE_DIRS or is_gitignored(full_path)


def file_is_ignored(full_path):
    return is_gitignored(full_path)


def content_is_skippable(rel_path, filename):
    if filename in SKIP_CONTENT_FILES or not is_valid_ext(filename):
        return True
    # Нормализация нужна для путей из Windows (\) и настроек с /.
    rel = rel_path.replace("\\", "/")
    return any(
        rel.startswith(d.replace("\\", "/").rstrip("/") + "/")
        for d in SKIP_CONTENT_DIRS
    )


def generate_tree(root_path="."):
    def build_tree(current_dir, prefix=""):
        lines = []
        try:
            items = os.listdir(current_dir)
        except OSError:
            return lines
        dirs = sorted(
            d
            for d in items
            if os.path.isdir(os.path.join(current_dir, d))
            and not dir_is_excluded(d, os.path.join(current_dir, d))
        )
        files = sorted(
            f
            for f in items
            if os.path.isfile(os.path.join(current_dir, f))
            and not file_is_ignored(os.path.join(current_dir, f))
        )
        all_entries = [(d, True) for d in dirs] + [(f, False) for f in files]
        for i, (name, is_dir) in enumerate(all_entries):
            is_last = i == len(all_entries) - 1
            lines.append(
                f"{prefix}{TREE_LAST if is_last else TREE_BRANCH}{name}{'/' if is_dir else ''}"
            )
            if is_dir:
                new_prefix = prefix + (TREE_SPACE if is_last else TREE_VERT)
                lines.extend(build_tree(os.path.join(current_dir, name), new_prefix))
        return lines

    root_name = (
        "./" if root_path == "." else f"{os.path.basename(os.path.abspath(root_path))}/"
    )
    return "\n".join([root_name] + build_tree(root_path))


def generate_file_contents(
    root_path=".", clean=False, use_keywords=True, use_format_regex=True
):
    content_lines = []
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if not dir_is_excluded(d, os.path.join(root, d))]
        dirs.sort()
        for filename in sorted(files):
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, root_path)
            if content_is_skippable(rel_path, filename) or file_is_ignored(filepath):
                continue
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError) as e:
                content_lines.append(f"\n## {rel_path}\n```{e}```\n")
                continue
            if use_keywords or use_format_regex:
                content = redact_secrets(
                    content,
                    filename=filename,
                    filename_for_log=rel_path,
                    use_keywords=use_keywords,
                    use_format_regex=use_format_regex,
                )
            if clean:
                content = clean_code(content, filename)
            content_lines.append(f"\n## {rel_path}\n")
            content_lines.append(f"```{get_lang(filename)}\n{content}\n```\n")
    return "\n".join(content_lines)


def render_redaction_report():
    if not REDACTION_LOG:
        return "\n\n---\n\n# Отредактированные секреты\n\nНичего не найдено/заменено.\n"
    lines = ["\n\n---\n\n# Отредактированные секреты\n"]
    total = 0
    for rel_path, hits in sorted(REDACTION_LOG.items()):
        lines.append(f"\n## {rel_path}\n")
        for h in hits:
            total += 1
            lines.append(f"- {h}\n")
    lines.insert(1, f"\nВсего заменено: {total}\n")
    return "".join(lines)


def run_full_mode(clean=False, use_keywords=True, use_format_regex=True):
    REDACTION_LOG.clear()
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("# Project Structure\n\n## Directory Tree\n\n```\n")
        f.write(generate_tree("."))
        f.write("\n```\n\n---\n\n# File Contents\n")
        f.write(
            generate_file_contents(
                ".",
                clean=clean,
                use_keywords=use_keywords,
                use_format_regex=use_format_regex,
            )
        )
        f.write(render_redaction_report())
    size = os.path.getsize(OUTPUT_FILE)
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        full_text = f.read()
    print(
        f"SUCCESS! Size: {size / 1024:.2f} KB, tokens ({TOKEN_MODE}): {count_tokens(full_text)}"
    )


class Node:
    __slots__ = ("children", "expanded", "is_dir", "name", "parent", "path", "selected")

    def __init__(self, name, path, is_dir, parent=None):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.parent = parent
        self.children = []
        self.expanded = False
        self.selected = False

    def load_children(self):
        if self.children:
            return
        try:
            items = os.listdir(self.path)
        except OSError:
            return
        dirs = sorted(
            d
            for d in items
            if os.path.isdir(os.path.join(self.path, d))
            and not dir_is_excluded(d, os.path.join(self.path, d))
        )
        files = sorted(
            f
            for f in items
            if os.path.isfile(os.path.join(self.path, f))
            and not file_is_ignored(os.path.join(self.path, f))
        )
        for d in dirs:
            self.children.append(Node(d, os.path.join(self.path, d), True, self))
        for f in files:
            self.children.append(Node(f, os.path.join(self.path, f), False, self))


def flatten(node, depth=0, out=None):
    if out is None:
        out = []
    out.append((node, depth))
    if node.is_dir and node.expanded:
        for c in node.children:
            flatten(c, depth + 1, out)
    return out


def set_selected_recursive(node, value):
    node.selected = value
    if node.is_dir:
        node.load_children()
        for c in node.children:
            set_selected_recursive(c, value)


def collect_selected_files(node, acc):
    if not node.is_dir:
        if node.selected:
            acc.append(node.path)
        return
    if not node.children and node.selected:
        node.load_children()
    for c in node.children:
        collect_selected_files(c, acc)


def estimate_tokens_for_selection(node):
    files = []
    collect_selected_files(node, files)
    total_chars = 0
    for fp in files:
        try:
            total_chars += os.path.getsize(fp)
        except OSError:
            pass
    return len(files), max(1, total_chars // 4)


def apply_profile_selection(root, rel_files):
    # В профилях сохраняем переносимые пути с /, включая профили из Linux.
    rel_set = {p.replace("\\", "/") for p in rel_files}

    def mark(node):
        rel = os.path.relpath(node.path, ".").replace("\\", "/")
        if not node.is_dir:
            if rel in rel_set:
                node.selected = True
            return
        node.load_children()
        if any(rf == rel or rf.startswith(rel + "/") for rf in rel_set):
            node.expanded = True
        for c in node.children:
            mark(c)

    mark(root)


def load_profiles():
    if not os.path.exists(PROFILES_FILE):
        return {}
    with open(PROFILES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _new_picker_root(initial_selection):
    root = Node(".", ".", True)
    root.expanded = True
    root.load_children()
    if initial_selection:
        apply_profile_selection(root, initial_selection)
    return root


def _move_picker(root, cursor, visible, key):
    node, _ = visible[cursor]
    if key == "up":
        cursor = max(0, cursor - 1)
    elif key == "down":
        cursor = min(len(visible) - 1, cursor + 1)
    elif key == "right":
        if node.is_dir:
            node.load_children()
            node.expanded = True
    elif key == "left":
        if node.is_dir and node.expanded and node.children:
            node.expanded = False
        elif node.parent is not None:
            for i, (other, _) in enumerate(visible):
                if other is node.parent:
                    cursor = i
                    break
            node.parent.expanded = False
    elif key == "space":
        set_selected_recursive(node, not node.selected)
    return cursor


def windows_picker(initial_selection=None):
    root = _new_picker_root(initial_selection)
    cursor = top = 0
    while True:
        visible = flatten(root)
        cursor = min(cursor, len(visible) - 1)
        width, height = shutil.get_terminal_size((100, 25))
        page = max(1, height - 5)
        top = min(top, cursor)
        if cursor >= top + page:
            top = cursor - page + 1
        n_files, approx_tokens = estimate_tokens_for_selection(root)
        os.system("cls")
        print("↑/↓ или j/k: выбор | →/Enter: открыть | ←/Backspace: назад")
        print("Пробел: отметить | F: готово | Q: выход")
        print(
            f"Файлов: {n_files} | ~токенов: {approx_tokens} | {cursor + 1}/{len(visible)}"
        )
        for idx in range(top, min(top + page, len(visible))):
            node, depth = visible[idx]
            mark = "[x]" if node.selected else "[ ]"
            arrow = ("v " if node.expanded else "> ") if node.is_dir else ""
            line = (
                f"{'  ' * depth}{mark} {arrow}{node.name}{'/' if node.is_dir else ''}"
            )
            print(("> " if idx == cursor else "  ") + line[: max(1, width - 3)])
        print("-" * min(width, 60))
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            scan = msvcrt.getwch()
            key = {"H": "up", "P": "down", "M": "right", "K": "left"}.get(scan)
        else:
            key = {
                "k": "up",
                "j": "down",
                "l": "right",
                "h": "left",
                "\r": "right",
                "\x08": "left",
                " ": "space",
                "f": "finish",
                "q": "quit",
            }.get(ch.lower())
        if key == "quit" or ch == "\x03":
            return None, None
        if key == "finish":
            break
        cursor = _move_picker(root, cursor, visible, key)
    selected_files = []
    collect_selected_files(root, selected_files)
    return root, selected_files


def picker(stdscr, initial_selection=None):
    curses.curs_set(0)
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    curses.init_pair(1, curses.COLOR_GREEN, bg)
    curses.init_pair(2, curses.COLOR_YELLOW, bg)
    root = _new_picker_root(initial_selection)
    cursor = top = 0
    while True:
        visible = flatten(root)
        cursor = min(cursor, len(visible) - 1)
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        if h < 4 or w < 10:
            stdscr.refresh()
            continue
        header = "up/down move  right/Enter open  left/Backspace close/up  Space select  F finish  Q quit"
        stdscr.addnstr(0, 0, header, w - 1, curses.A_BOLD)
        n_files, approx_tokens = estimate_tokens_for_selection(root)
        status = f"Selected files: {n_files}  ~tokens (approx): {approx_tokens}"
        stdscr.addnstr(h - 1, 0, status, w - 1, curses.color_pair(2))
        page = max(1, h - 2)
        top = min(top, cursor)
        if cursor >= top + page:
            top = cursor - page + 1
        for row, (node, depth) in enumerate(visible[top : top + page]):
            idx = top + row
            mark = "[x]" if node.selected else "[ ]"
            arrow = ("v " if node.expanded else "> ") if node.is_dir else ""
            name = node.name + ("/" if node.is_dir else "")
            line = f"{'  ' * depth}{mark} {arrow}{name}"
            attr = curses.A_REVERSE if idx == cursor else 0
            if node.selected:
                attr |= curses.color_pair(1)
            stdscr.addnstr(row + 1, 0, line, w - 1, attr)
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("q"), ord("Q")):
            return None, None
        if key in (ord("f"), ord("F")):
            break
        action = None
        if key in (curses.KEY_UP, ord("k")):
            action = "up"
        elif key in (curses.KEY_DOWN, ord("j")):
            action = "down"
        elif key in (curses.KEY_RIGHT, ord("l"), 10, 13):
            action = "right"
        elif key in (curses.KEY_LEFT, ord("h"), curses.KEY_BACKSPACE, 127):
            action = "left"
        elif key == ord(" "):
            action = "space"
        cursor = _move_picker(root, cursor, visible, action)
    selected_files = []
    collect_selected_files(root, selected_files)
    return root, selected_files


def build_sparse_tree(root):
    lines = []

    def has_selected_descendant(node):
        if not node.is_dir:
            return node.selected
        return any(has_selected_descendant(c) for c in node.children)

    def walk(node, prefix=""):
        relevant = [
            c for c in node.children if c.selected or has_selected_descendant(c)
        ]
        for i, c in enumerate(relevant):
            is_last = i == len(relevant) - 1
            lines.append(
                f"{prefix}{TREE_LAST if is_last else TREE_BRANCH}{c.name}{'/' if c.is_dir else ''}"
            )
            if c.is_dir:
                walk(c, prefix + (TREE_SPACE if is_last else TREE_VERT))

    lines.append("./")
    walk(root)
    return "\n".join(lines)


def save_profile(selected_files, clean, use_keywords, use_format_regex):
    profiles = load_profiles()
    name = input("Profile name to save (Enter = skip): ").strip()
    if not name:
        return
    rel_files = sorted(
        {os.path.relpath(fp, ".").replace("\\", "/") for fp in selected_files}
    )
    profiles[name] = {
        "files": rel_files,
        "clean": clean,
        "use_keywords": use_keywords,
        "use_format_regex": use_format_regex,
    }
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)
    print(f"Profile '{name}' saved to {PROFILES_FILE}")


def choose_profile_to_load():
    profiles = load_profiles()
    if not profiles:
        return None
    names = list(profiles.keys())
    print("Доступные профили:", ", ".join(names))
    name = input("Загрузить профиль (Enter = обычный выбор в дереве): ").strip()
    if not name or name not in profiles:
        return None
    return profiles[name]


DEFAULT_PROFILE_SETTINGS = {
    "clean": True,
    "use_keywords": True,
    "use_format_regex": True,
}


def run_interactive_mode():
    REDACTION_LOG.clear()
    profile = choose_profile_to_load()
    initial_selection = profile["files"] if profile is not None else None
    root, selected_files = (
        windows_picker(initial_selection)
        if os.name == "nt"
        else curses.wrapper(picker, initial_selection)
    )
    if root is None:
        print("Cancelled.")
        return
    if not selected_files:
        print("Nothing selected.")
        return
    settings = profile if profile is not None else DEFAULT_PROFILE_SETTINGS
    use_defaults = False
    if profile is not None:
        use_defaults = (
            input(
                f"Использовать настройки профиля (clean={settings['clean']}, "
                f"keywords={settings['use_keywords']}, format_regex={settings['use_format_regex']})? [Y/n]: "
            )
            .strip()
            .lower()
            != "n"
        )
    if use_defaults:
        clean = settings["clean"]
        use_keywords = settings["use_keywords"]
        use_format_regex = settings["use_format_regex"]
    else:
        mode = input("Content mode: [c]lean or [r]aw? [c/r]: ").strip().lower()
        clean = mode != "r"
        use_keywords = (
            input("Redact secrets by keyword (SECRET/TOKEN/PASSWORD/...)? [Y/n]: ")
            .strip()
            .lower()
            != "n"
        )
        use_format_regex = (
            input(
                "Also redact by known secret formats (AWS/GitHub/OpenAI/JWT/conn string)? [Y/n]: "
            )
            .strip()
            .lower()
            != "n"
        )
    tree_text = build_sparse_tree(root)
    content_lines = []
    skipped = []
    for filepath in sorted(set(selected_files)):
        rel_path = os.path.relpath(filepath, ".")
        filename = os.path.basename(filepath)
        if content_is_skippable(rel_path, filename):
            skipped.append(rel_path)
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as e:
            content_lines.append(f"\n## {rel_path}\n```{e}```\n")
            continue
        if use_keywords or use_format_regex:
            content = redact_secrets(
                content,
                filename=filename,
                filename_for_log=rel_path,
                use_keywords=use_keywords,
                use_format_regex=use_format_regex,
            )
        if clean:
            content = clean_code(content, filename)
        content_lines.append(f"\n## {rel_path}\n")
        content_lines.append(f"```{get_lang(filename)}\n{content}\n```\n")
    full_text = (
        "# Project Structure (selected)\n\n## Directory Tree\n\n```\n"
        + tree_text
        + "\n```\n\n---\n\n# File Contents\n"
        + "\n".join(content_lines)
        + render_redaction_report()
    )
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(full_text)
    size = os.path.getsize(OUTPUT_FILE)
    print(
        f"SUCCESS! Size: {size / 1024:.2f} KB, files: {len(selected_files) - len(skipped)}, "
        f"tokens ({TOKEN_MODE}): {count_tokens(full_text)}"
    )
    if skipped:
        print(
            "Пропущено (в skip_content_files/skip_content_dirs/недопустимое расширение): "
            + ", ".join(skipped)
        )
    if (
        input("Save this file selection as a reusable profile? [y/N]: ").strip().lower()
        == "y"
    ):
        save_profile(selected_files, clean, use_keywords, use_format_regex)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--interactive", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--no-gitignore", action="store_true")
    parser.add_argument(
        "--no-redact-keywords",
        action="store_true",
        help="Не искать секреты по ключевым словам (SECRET/TOKEN/PASSWORD/...)",
    )
    parser.add_argument(
        "--no-redact-format",
        action="store_true",
        help="Не искать секреты по формату значения (AWS/GitHub/OpenAI/JWT/conn string)",
    )
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="Полностью выключить редактирование секретов",
    )
    args = parser.parse_args()
    global USE_GITIGNORE, GITIGNORE
    if args.no_gitignore:
        USE_GITIGNORE = False
        GITIGNORE = None
    if not HAS_PATHSPEC and CFG.get("use_gitignore", True) and not args.no_gitignore:
        warn(
            "пакет 'pathspec' не установлен (uv add pathspec), .gitignore не будет учитываться."
        )
    if args.interactive:
        run_interactive_mode()
    else:
        print("Generating structure...")
        run_full_mode(
            clean=args.clean,
            use_keywords=not (args.no_redact or args.no_redact_keywords),
            use_format_regex=not (args.no_redact or args.no_redact_format),
        )


if __name__ == "__main__":
    main()
