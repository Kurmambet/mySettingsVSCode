import os
import re

# Директории для исключения из обхода
EXCLUDE_DIRS = {
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
}

SKIP_CONTENT_DIRS = {
    "alembic/versions",
    "backend/alembic",
    "node_modules",
    ".vscode",
    # "media",
    # "tus",
    "public",
    # "core",
    # "utils",
    ".venv",
    # "api",
    # "stores",
    # "constants",
}

SKIP_CONTENT_FILES = {
    ".dockerignore",
    "uv.lock",
    ".gitignore",
    "alembic.ini",
    ".md",
    "README.md",
    "README",
    "notes.txt",
    "project_structure.md",
    "package-lock.json",
    ".woff2",
    "tsconfig.node.json",
    "tsconfig.json",
    "tsconfig.app.json",
    "tree.py",
    "docker-compose.dev.yml",
    "Dockerfile",
    ".env.example",
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
}

INCLUDE_EXTENSIONS = {
    ".py",
    ".conf",
    # ".txt",
    # ".md",
    ".yml",
    ".yaml",
    ".toml",
    ".json",
    ".js",
    ".ts",
    ".vue",
    ".html",
    ".css",
    # ".env.example",
    ".dockerignore",
    "Dockerfile",
    ".tsx",
}

OUTPUT_FILE = "project_structure.md"


def clean_code(content, filename):
    """Универсальная очистка кода от комментариев и лишних строк."""
    ext = os.path.splitext(filename)[1]

    # 1. Сначала удаляем многострочные комментарии (/* */ для JS/CSS и docstrings для Python)
    if ext in [".js", ".ts", ".css", ".vue"]:
        content = re.sub(r"/\*[\s\S]*?\*/", "", content)
    elif ext == ".py":
        # Удаляем многострочные кавычки '''...''' и """..."""
        content = re.sub(r'""".*?"""', "", content, flags=re.DOTALL)
        content = re.sub(r"'''.*?'''", "", content, flags=re.DOTALL)

    lines = content.split("\n")
    cleaned_lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Правило: Всегда сохраняем самую первую строку файла (путь)
        if i == 0 and (
            stripped.startswith("#")
            or stripped.startswith("//")
            or stripped.startswith("/*")
        ):
            cleaned_lines.append(line)
            continue

        # Пропускаем пустые строки
        if not stripped:
            continue

        if ext in [".js", ".ts", ".css", ".vue"]:
            # Удаляем строки, состоящие только из //
            if stripped.startswith("//"):
                continue
            # Удаляем инлайновые //, если перед ними НЕ стоит двоеточие (защита http://)
            # Ищем //, перед которыми есть пробел или начало кода, но не ':'
            line = re.sub(r"(?<!:)\/\/.*", "", line)

        elif ext in [".py", ".yml", ".yaml", ".toml"]:
            # Удаляем строки, состоящие только из #
            if stripped.startswith("#"):
                continue
            # Удаляем инлайновые #, если перед ними есть пробел (стандарт PEP8 и YAML)
            if " #" in line:
                line = line.split(" #")[0]

        # Если после очистки инлайна строка стала пустой — пропускаем
        if line.strip():
            cleaned_lines.append(line.rstrip())

    return "\n".join(cleaned_lines)


def get_file_extension(filename):
    ext_map = {
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
    if filename == "Dockerfile":
        return "dockerfile"
    for ext, lang in ext_map.items():
        if filename.endswith(ext):
            return lang
    return "text"


def generate_tree(root_path="."):
    """Генерирует красивое дерево проекта с использованием символов веток."""

    def build_tree(current_dir, prefix=""):
        lines = []
        try:
            # Получаем список всех элементов и фильтруем исключенные папки
            items = os.listdir(current_dir)
            dirs = sorted(
                [
                    d
                    for d in items
                    if os.path.isdir(os.path.join(current_dir, d))
                    and d not in EXCLUDE_DIRS
                ]
            )
            files = sorted(
                [f for f in items if os.path.isfile(os.path.join(current_dir, f))]
            )

            all_entries = [(d, True) for d in dirs] + [(f, False) for f in files]
            count = len(all_entries)

            for i, (name, is_dir) in enumerate(all_entries):
                is_last = i == count - 1
                connector = "└── " if is_last else "├── "

                # Добавляем строку для текущего элемента
                lines.append(f"{prefix}{connector}{name}{'/' if is_dir else ''}")

                # Если это директория, идем глубже
                if is_dir:
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    lines.extend(
                        build_tree(os.path.join(current_dir, name), new_prefix)
                    )
        except PermissionError:
            pass
        return lines

    root_name = (
        "./" if root_path == "." else f"{os.path.basename(os.path.abspath(root_path))}/"
    )
    return "\n".join([root_name] + build_tree(root_path))


def generate_file_contents(root_path="."):
    content_lines = []
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        dirs.sort()
        for filename in sorted(files):
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, root_path)

            if filename in SKIP_CONTENT_FILES:
                continue

            # Проверка расширения
            is_valid_ext = (
                any(filename.endswith(ext) for ext in INCLUDE_EXTENSIONS)
                or filename == "Dockerfile"
            )
            if not is_valid_ext:
                continue

            # Проверка исключенных директорий (alembic и т.д.)
            if any(
                rel_path.startswith(d.replace("/", os.sep)) for d in SKIP_CONTENT_DIRS
            ):
                continue

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                # cleaned = clean_code(content, filename)
                lang = get_file_extension(filename)

                content_lines.append(f"\n## {rel_path}\n")
                content_lines.append(f"```{lang}\n{content}\n```\n")
            except Exception as e:
                content_lines.append(f"\n## {rel_path}\n```{e}```\n")
    return "\n".join(content_lines)


def main():
    print("Generating structure...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("# Project Structure\n\n## Directory Tree\n\n```")
        f.write(generate_tree("."))
        f.write("\n```\n\n---\n\n# File Contents\n")
        f.write(generate_file_contents("."))

    size = os.path.getsize(OUTPUT_FILE)
    print(f"SUCCESS! Size: {size / 1024:.2f} KB")


if __name__ == "__main__":
    main()
