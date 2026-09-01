#!/usr/bin/env python3

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


# ============================================================
# CONFIGURATION
# ============================================================

API = "https://api.github.com"

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
USERNAME = os.environ.get("GITHUB_USERNAME", "").strip()

if not USERNAME:
    raise SystemExit("GITHUB_USERNAME is required.")


HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
    "User-Agent": "github-tech-stack-stats",
}

if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


# Files that can reveal the technology stack.
INTERESTING_FILES = {
    "package.json",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "pipfile",
    "composer.json",
    "gemfile",
    "go.mod",
    "cargo.toml",

    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",

    "vercel.json",

    "vite.config.js",
    "vite.config.ts",
    "vite.config.mjs",

    "next.config.js",
    "next.config.ts",
    "next.config.mjs",

    "astro.config.js",
    "astro.config.ts",
    "astro.config.mjs",

    "angular.json",

    "tailwind.config.js",
    "tailwind.config.ts",
    "tailwind.config.mjs",

    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
}


# ============================================================
# HTTP / GITHUB API
# ============================================================

def github_get(path: str, params: dict | None = None):

    url = API + path

    if params:
        url += "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        url,
        headers=HEADERS
    )

    for attempt in range(5):

        try:

            with urllib.request.urlopen(request, timeout=30) as response:

                return json.loads(
                    response.read().decode("utf-8")
                )

        except urllib.error.HTTPError as error:

            # Not found
            if error.code == 404:
                return None

            # Rate limit
            if error.code in (403, 429):

                retry_after = error.headers.get("Retry-After")

                if retry_after and retry_after.isdigit():
                    wait = int(retry_after)
                else:
                    wait = 5 * (attempt + 1)

                print(
                    f"[INFO] GitHub API rate limit. "
                    f"Waiting {wait}s..."
                )

                time.sleep(wait)
                continue

            raise

        except (
            urllib.error.URLError,
            TimeoutError
        ):

            if attempt == 4:
                raise

            time.sleep(2 ** attempt)

    return None


# ============================================================
# REPOSITORIES
# ============================================================

def list_repositories():

    repositories = []

    page = 1

    while True:

        if TOKEN:

            data = github_get(
                "/user/repos",
                {
                    "per_page": 100,
                    "page": page,
                    "affiliation": "owner",
                    "sort": "updated",
                    "direction": "desc",
                }
            )

        else:

            data = github_get(
                f"/users/{urllib.parse.quote(USERNAME)}/repos",
                {
                    "per_page": 100,
                    "page": page,
                    "type": "owner",
                    "sort": "updated",
                    "direction": "desc",
                }
            )

        if not data:
            break

        repositories.extend(data)

        if len(data) < 100:
            break

        page += 1

    # Ignore forks and archived repositories.
    repositories = [
        repo
        for repo in repositories
        if not repo.get("fork", False)
        and not repo.get("archived", False)
    ]

    return repositories


# ============================================================
# FILE CONTENT
# ============================================================

def get_file_content(repository, path):

    repository_name = repository["name"]

    encoded_path = urllib.parse.quote(
        path,
        safe="/"
    )

    data = github_get(
        f"/repos/{USERNAME}/{repository_name}/contents/{encoded_path}"
    )

    if not data:
        return ""

    if data.get("type") != "file":
        return ""

    content = data.get("content", "")

    if not content:
        return ""

    try:

        return base64.b64decode(
            content
        ).decode(
            "utf-8",
            errors="ignore"
        )

    except Exception:

        return ""


# ============================================================
# REPOSITORY TREE
# ============================================================

def get_repository_tree(repository):

    repository_name = repository["name"]

    branch = repository.get(
        "default_branch"
    ) or "main"

    encoded_branch = urllib.parse.quote(
        branch,
        safe=""
    )

    data = github_get(
        f"/repos/{USERNAME}/{repository_name}/git/trees/{encoded_branch}",
        {
            "recursive": "1"
        }
    )

    if not data:
        return []

    return [
        item.get("path", "")
        for item in data.get("tree", [])
        if item.get("type") == "blob"
    ]


# ============================================================
# LANGUAGE STATISTICS
# ============================================================

def get_languages(repository):

    repository_name = repository["name"]

    data = github_get(
        f"/repos/{USERNAME}/{repository_name}/languages"
    )

    if not data:
        return {}

    return data


def calculate_percentages(counter):

    total = sum(counter.values())

    if total == 0:
        return {}

    return {
        name: round(
            value * 100 / total,
            2
        )
        for name, value
        in counter.most_common()
    }


# ============================================================
# TECHNOLOGY DETECTION
# ============================================================

def add_technology(found, category, technology):

    found[category].add(technology)


def package_exists(package_data, names):

    dependencies = {}

    for section in (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
    ):

        section_data = package_data.get(
            section,
            {}
        )

        if isinstance(section_data, dict):
            dependencies.update(section_data)

    dependency_names = {
        name.lower()
        for name in dependencies
    }

    return any(
        name.lower() in dependency_names
        for name in names
    )


def detect_package_json(text, found):

    try:

        package_data = json.loads(text)

    except Exception:

        return

    # --------------------------------------------------------
    # Frameworks
    # --------------------------------------------------------

    if package_exists(
        package_data,
        ["react", "react-dom"]
    ):
        add_technology(
            found,
            "Frameworks",
            "React"
        )

    if package_exists(
        package_data,
        ["next"]
    ):
        add_technology(
            found,
            "Frameworks",
            "Next.js"
        )

    if package_exists(
        package_data,
        ["vue"]
    ):
        add_technology(
            found,
            "Frameworks",
            "Vue"
        )

    if package_exists(
        package_data,
        ["nuxt"]
    ):
        add_technology(
            found,
            "Frameworks",
            "Nuxt"
        )

    if package_exists(
        package_data,
        ["@angular/core"]
    ):
        add_technology(
            found,
            "Frameworks",
            "Angular"
        )

    if package_exists(
        package_data,
        ["svelte"]
    ):
        add_technology(
            found,
            "Frameworks",
            "Svelte"
        )

    if package_exists(
        package_data,
        ["astro"]
    ):
        add_technology(
            found,
            "Frameworks",
            "Astro"
        )

    if package_exists(
        package_data,
        ["express"]
    ):
        add_technology(
            found,
            "Frameworks",
            "Express"
        )

    # --------------------------------------------------------
    # Runtime
    # --------------------------------------------------------

    if package_exists(
        package_data,
        ["node"]
    ):
        add_technology(
            found,
            "Runtime",
            "Node.js"
        )

    # Most Node projects implicitly use Node.js.
    if (
        "scripts" in package_data
        or "dependencies" in package_data
        or "devDependencies" in package_data
    ):
        add_technology(
            found,
            "Runtime",
            "Node.js"
        )

    if package_exists(
        package_data,
        ["bun"]
    ):
        add_technology(
            found,
            "Runtime",
            "Bun"
        )

    # --------------------------------------------------------
    # Styling
    # --------------------------------------------------------

    if package_exists(
        package_data,
        ["tailwindcss"]
    ):
        add_technology(
            found,
            "Styling",
            "Tailwind CSS"
        )

    if package_exists(
        package_data,
        ["bootstrap"]
    ):
        add_technology(
            found,
            "Styling",
            "Bootstrap"
        )

    # --------------------------------------------------------
    # Build tools
    # --------------------------------------------------------

    if package_exists(
        package_data,
        ["vite"]
    ):
        add_technology(
            found,
            "Build Tools",
            "Vite"
        )

    if package_exists(
        package_data,
        ["webpack"]
    ):
        add_technology(
            found,
            "Build Tools",
            "Webpack"
        )

    if package_exists(
        package_data,
        ["babel", "@babel/core"]
    ):
        add_technology(
            found,
            "Build Tools",
            "Babel"
        )

    # --------------------------------------------------------
    # Automation
    # --------------------------------------------------------

    if package_exists(
        package_data,
        ["n8n"]
    ):
        add_technology(
            found,
            "Automation",
            "n8n"
        )

    # --------------------------------------------------------
    # AI
    # --------------------------------------------------------

    if package_exists(
        package_data,
        ["openai"]
    ):
        add_technology(
            found,
            "AI",
            "OpenAI"
        )

    if package_exists(
        package_data,
        ["ollama"]
    ):
        add_technology(
            found,
            "AI",
            "Ollama"
        )

    if package_exists(
        package_data,
        ["langchain", "@langchain/core"]
    ):
        add_technology(
            found,
            "AI",
            "LangChain"
        )

    if package_exists(
        package_data,
        ["@xenova/transformers"]
    ):
        add_technology(
            found,
            "AI",
            "Transformers.js"
        )

    # --------------------------------------------------------
    # Database
    # --------------------------------------------------------

    if package_exists(
        package_data,
        ["pg"]
    ):
        add_technology(
            found,
            "Databases",
            "PostgreSQL"
        )

    if package_exists(
        package_data,
        ["mysql", "mysql2"]
    ):
        add_technology(
            found,
            "Databases",
            "MySQL"
        )

    if package_exists(
        package_data,
        ["mongodb", "mongoose"]
    ):
        add_technology(
            found,
            "Databases",
            "MongoDB"
        )

    if package_exists(
        package_data,
        ["sqlite3", "better-sqlite3"]
    ):
        add_technology(
            found,
            "Databases",
            "SQLite"
        )

    if package_exists(
        package_data,
        ["redis", "ioredis"]
    ):
        add_technology(
            found,
            "Databases",
            "Redis"
        )

    # --------------------------------------------------------
    # Testing
    # --------------------------------------------------------

    if package_exists(
        package_data,
        ["jest"]
    ):
        add_technology(
            found,
            "Testing",
            "Jest"
        )

    if package_exists(
        package_data,
        ["vitest"]
    ):
        add_technology(
            found,
            "Testing",
            "Vitest"
        )


# ============================================================
# PYTHON DETECTION
# ============================================================

def detect_python_requirements(text, found):

    lines = text.lower().splitlines()

    packages = set()

    for line in lines:

        line = line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        # Remove version specifiers.
        package = re.split(
            r"[<>=!~;\[\]]",
            line
        )[0].strip()

        if package:
            packages.add(package)


    if "django" in packages:
        add_technology(
            found,
            "Frameworks",
            "Django"
        )

    if "flask" in packages:
        add_technology(
            found,
            "Frameworks",
            "Flask"
        )

    if "fastapi" in packages:
        add_technology(
            found,
            "Frameworks",
            "FastAPI"
        )

    if "pandas" in packages:
        add_technology(
            found,
            "Data / ML",
            "Pandas"
        )

    if "numpy" in packages:
        add_technology(
            found,
            "Data / ML",
            "NumPy"
        )

    if (
        "scikit-learn" in packages
        or "sklearn" in packages
    ):
        add_technology(
            found,
            "Data / ML",
            "Scikit-learn"
        )

    if (
        "tensorflow" in packages
        or "tensorflow-gpu" in packages
    ):
        add_technology(
            found,
            "AI",
            "TensorFlow"
        )

    if "torch" in packages:
        add_technology(
            found,
            "AI",
            "PyTorch"
        )

    if "ultralytics" in packages:
        add_technology(
            found,
            "AI",
            "YOLO / Ultralytics"
        )

    if "openai" in packages:
        add_technology(
            found,
            "AI",
            "OpenAI"
        )

    if "ollama" in packages:
        add_technology(
            found,
            "AI",
            "Ollama"
        )

    if (
        "langchain"
        in packages
        or "langchain-core"
        in packages
    ):
        add_technology(
            found,
            "AI",
            "LangChain"
        )

    if (
        "psycopg2"
        in packages
        or "psycopg2-binary"
        in packages
        or "psycopg"
        in packages
    ):
        add_technology(
            found,
            "Databases",
            "PostgreSQL"
        )

    if (
        "pymysql"
        in packages
        or "mysqlclient"
        in packages
    ):
        add_technology(
            found,
            "Databases",
            "MySQL"
        )

    if (
        "pymongo"
        in packages
        or "mongoengine"
        in packages
    ):
        add_technology(
            found,
            "Databases",
            "MongoDB"
        )

    if (
        "redis"
        in packages
        or "redis-py"
        in packages
    ):
        add_technology(
            found,
            "Databases",
            "Redis"
        )

    if (
        "sqlalchemy"
        in packages
    ):
        add_technology(
            found,
            "Databases",
            "SQLAlchemy"
        )

    if (
        "pytest"
        in packages
    ):
        add_technology(
            found,
            "Testing",
            "Pytest"
        )


# ============================================================
# DOCKER DETECTION
# ============================================================

def detect_docker(text, found):

    low = text.lower()

    if (
        "postgres"
        in low
        or "postgresql"
        in low
    ):
        add_technology(
            found,
            "Databases",
            "PostgreSQL"
        )

    if "mysql" in low:
        add_technology(
            found,
            "Databases",
            "MySQL"
        )

    if (
        "mongo"
        in low
        or "mongodb"
        in low
    ):
        add_technology(
            found,
            "Databases",
            "MongoDB"
        )

    if "redis" in low:
        add_technology(
            found,
            "Databases",
            "Redis"
        )

    if (
        "n8nio/n8n"
        in low
        or re.search(
            r"\bn8n\b",
            low
        )
    ):
        add_technology(
            found,
            "Automation",
            "n8n"
        )

    if "ollama" in low:
        add_technology(
            found,
            "AI",
            "Ollama"
        )

    if (
        "openai"
        in low
    ):
        add_technology(
            found,
            "AI",
            "OpenAI"
        )


# ============================================================
# CONFIG FILE DETECTION
# ============================================================

def detect_config_file(path, text, found):

    filename = PurePosixPath(
        path
    ).name.lower()

    if filename.startswith(
        "vite.config"
    ):
        add_technology(
            found,
            "Build Tools",
            "Vite"
        )

    if filename.startswith(
        "next.config"
    ):
        add_technology(
            found,
            "Frameworks",
            "Next.js"
        )

    if filename.startswith(
        "astro.config"
    ):
        add_technology(
            found,
            "Frameworks",
            "Astro"
        )

    if filename == "angular.json":
        add_technology(
            found,
            "Frameworks",
            "Angular"
        )

    if filename.startswith(
        "tailwind.config"
    ):
        add_technology(
            found,
            "Styling",
            "Tailwind CSS"
        )

    if filename == "vercel.json":
        add_technology(
            found,
            "Cloud / Hosting",
            "Vercel"
        )


# ============================================================
# REPOSITORY ANALYSIS
# ============================================================

def analyze_repository(repository):

    languages = get_languages(
        repository
    )

    paths = get_repository_tree(
        repository
    )

    found = defaultdict(set)

    # --------------------------------------------------------
    # Structural detections
    # --------------------------------------------------------

    if any(
        path.startswith(
            ".github/workflows/"
        )
        for path in paths
    ):

        add_technology(
            found,
            "DevOps",
            "GitHub Actions"
        )

    if any(
        PurePosixPath(path).name.lower()
        == "dockerfile"
        for path in paths
    ):

        add_technology(
            found,
            "DevOps",
            "Docker"
        )

    if any(
        PurePosixPath(path).name.lower()
        in {
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        }
        for path in paths
    ):

        add_technology(
            found,
            "DevOps",
            "Docker"
        )


    # --------------------------------------------------------
    # Select relevant files
    # --------------------------------------------------------

    interesting = []

    interesting_names = {
        filename.lower()
        for filename
        in INTERESTING_FILES
    }

    for path in paths:

        filename = PurePosixPath(
            path
        ).name.lower()

        if filename in interesting_names:

            interesting.append(path)


    # Limit API requests per repository.
    interesting = interesting[:25]


    # --------------------------------------------------------
    # Analyze files
    # --------------------------------------------------------

    for path in interesting:

        text = get_file_content(
            repository,
            path
        )

        if not text:
            continue

        filename = PurePosixPath(
            path
        ).name.lower()


        # package.json
        if filename == "package.json":

            detect_package_json(
                text,
                found
            )


        # Python dependencies
        elif filename in {
            "requirements.txt",
            "requirements-dev.txt",
            "pipfile",
        }:

            detect_python_requirements(
                text,
                found
            )


        # pyproject.toml
        elif filename == "pyproject.toml":

            detect_python_requirements(
                text,
                found
            )


        # Docker
        elif filename in {
            "dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        }:

            detect_docker(
                text,
                found
            )


        # Configuration files
        detect_config_file(
            path,
            text,
            found
        )


    return languages, found


# ============================================================
# SVG GENERATION
# ============================================================

def escape_xml(value):

    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def generate_svg(
    username,
    language_percentages,
    technologies,
    repository_count,
    public_count,
    private_count,
    generated_at
):

    width = 1000
    height = 720

    language_rows = []

    y = 180

    for language, percentage in list(
        language_percentages.items()
    )[:8]:

        bar_width = max(
            4,
            int(
                410
                * percentage
                / 100
            )
        )

        language_rows.append(
            f"""
            <text
                x="55"
                y="{y}"
                class="label"
            >
                {escape_xml(language)}
            </text>

            <rect
                x="185"
                y="{y - 16}"
                width="410"
                height="18"
                rx="9"
                class="track"
            />

            <rect
                x="185"
                y="{y - 16}"
                width="{bar_width}"
                height="18"
                rx="9"
                class="bar"
            />

            <text
                x="615"
                y="{y}"
                class="percentage"
            >
                {percentage:.1f}%
            </text>
            """
        )

        y += 43


    # --------------------------------------------------------
    # Technologies
    # --------------------------------------------------------

    technology_rows = []

    y = 180

    categories_order = [
        "Frameworks",
        "Runtime",
        "Automation",
        "AI",
        "Databases",
        "DevOps",
        "Styling",
        "Build Tools",
        "Data / ML",
        "Cloud / Hosting",
        "Testing",
    ]

    total_rows = 0

    for category in categories_order:

        if category not in technologies:
            continue

        values = technologies[
            category
        ]

        for technology, count in values.items():

            if total_rows >= 11:
                break

            technology_rows.append(
                f"""
                <text
                    x="700"
                    y="{y}"
                    class="technology"
                >
                    {escape_xml(technology)}
                </text>

                <text
                    x="925"
                    y="{y}"
                    text-anchor="end"
                    class="repo-count"
                >
                    {count} repos
                </text>
                """
            )

            y += 39
            total_rows += 1

        if total_rows >= 11:
            break


    return f"""<svg
xmlns="http://www.w3.org/2000/svg"
width="{width}"
height="{height}"
viewBox="0 0 {width} {height}"
role="img"
aria-label="GitHub Tech Stack statistics"
>

<rect
    width="1000"
    height="720"
    rx="26"
    fill="#0d1117"
/>

<rect
    x="1"
    y="1"
    width="998"
    height="718"
    rx="26"
    fill="none"
    stroke="#30363d"
/>


<!-- HEADER -->

<text
    x="55"
    y="58"
    class="title"
>
    GitHub Tech Stack
</text>

<text
    x="55"
    y="91"
    class="subtitle"
>
    @{escape_xml(username)}
</text>


<!-- SUMMARY -->

<text
    x="700"
    y="55"
    class="summary-number"
>
    {repository_count}
</text>

<text
    x="700"
    y="80"
    class="summary-label"
>
    repositories
</text>

<text
    x="805"
    y="55"
    class="summary-number"
>
    {public_count}
</text>

<text
    x="805"
    y="80"
    class="summary-label"
>
    public
</text>

<text
    x="900"
    y="55"
    class="summary-number"
>
    {private_count}
</text>

<text
    x="900"
    y="80"
    class="summary-label"
>
    private
</text>


<line
    x1="55"
    y1="120"
    x2="945"
    y2="120"
    stroke="#30363d"
/>


<!-- LANGUAGES -->

<text
    x="55"
    y="150"
    class="section"
>
    LANGUAGES
</text>

{''.join(language_rows)}


<!-- DIVIDER -->

<line
    x1="660"
    y1="145"
    x2="660"
    y2="620"
    stroke="#30363d"
/>


<!-- TECHNOLOGIES -->

<text
    x="700"
    y="150"
    class="section"
>
    TECHNOLOGIES
</text>

{''.join(technology_rows)}


<!-- FOOTER -->

<line
    x1="55"
    y1="650"
    x2="945"
    y2="650"
    stroke="#30363d"
/>

<text
    x="55"
    y="680"
    class="footer"
>
    Updated {escape_xml(generated_at)}
</text>

<text
    x="945"
    y="680"
    text-anchor="end"
    class="footer"
>
    GitHub Actions · Self-hosted
</text>


<style>

.title {{
    fill: #f0f6fc;
    font: 700 30px
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
}}

.subtitle {{
    fill: #8b949e;
    font: 400 16px
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
}}

.section {{
    fill: #58a6ff;
    font: 700 13px
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
    letter-spacing: 2px;
}}

.label {{
    fill: #c9d1d9;
    font: 500 14px
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
}}

.percentage {{
    fill: #8b949e;
    font: 600 13px
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
}}

.track {{
    fill: #21262d;
}}

.bar {{
    fill: #58a6ff;
}}

.technology {{
    fill: #c9d1d9;
    font: 600 14px
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
}}

.repo-count {{
    fill: #8b949e;
    font: 400 12px
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
}}

.summary-number {{
    fill: #f0f6fc;
    font: 700 19px
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
}}

.summary-label {{
    fill: #8b949e;
    font: 400 10px
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
}}

.footer {{
    fill: #6e7681;
    font: 400 11px
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
}}

</style>

</svg>
"""


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 60)
    print(" GitHub Tech Stack Stats")
    print("=" * 60)
    print("")

    print(
        f"[INFO] Analyzing GitHub user: {USERNAME}"
    )

    repositories = list_repositories()

    print(
        f"[INFO] Found {len(repositories)} repositories."
    )

    language_bytes = Counter()

    technology_repositories = defaultdict(
        Counter
    )

    repository_details = []

    public_count = 0
    private_count = 0


    # --------------------------------------------------------
    # Analyze repositories
    # --------------------------------------------------------

    for index, repository in enumerate(
        repositories,
        start=1
    ):

        repository_name = repository[
            "name"
        ]

        print(
            f"[{index}/{len(repositories)}] "
            f"Analyzing {repository_name}..."
        )

        try:

            languages, technologies = (
                analyze_repository(
                    repository
                )
            )

        except Exception as error:

            print(
                f"[WARN] Failed to analyze "
                f"{repository_name}: {error}"
            )

            continue


        # Language bytes
        language_bytes.update(
            languages
        )


        # Technologies
        for category, names in technologies.items():

            for technology in names:

                technology_repositories[
                    category
                ][technology] += 1


        # Visibility
        if repository.get(
            "private",
            False
        ):

            private_count += 1

        else:

            public_count += 1


        repository_details.append({

            "name": repository_name,

            "private": bool(
                repository.get(
                    "private"
                )
            ),

            "html_url": repository.get(
                "html_url"
            ),

            "languages": languages,

        })


    # --------------------------------------------------------
    # Percentages
    # --------------------------------------------------------

    language_percentages = (
        calculate_percentages(
            language_bytes
        )
    )


    # --------------------------------------------------------
    # Sort technologies
    # --------------------------------------------------------

    technologies_output = {}

    for category in sorted(
        technology_repositories.keys()
    ):

        technologies_output[
            category
        ] = dict(
            technology_repositories[
                category
            ].most_common()
        )


    # --------------------------------------------------------
    # Timestamp
    # --------------------------------------------------------

    generated_at = (
        datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    )


    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    output = {

        "username": USERNAME,

        "repositories_analyzed": len(
            repository_details
        ),

        "public_repositories": public_count,

        "private_repositories": private_count,

        "generated_at": generated_at,

        "languages": dict(
            language_bytes.most_common()
        ),

        "language_percentages":
            language_percentages,

        "technologies":
            technologies_output,

        "repositories":
            repository_details,

    }


    # --------------------------------------------------------
    # Create directories
    # --------------------------------------------------------

    Path(
        "assets"
    ).mkdir(
        exist_ok=True
    )

    Path(
        "data"
    ).mkdir(
        exist_ok=True
    )


    # --------------------------------------------------------
    # Write JSON
    # --------------------------------------------------------

    Path(
        "data/tech-stack.json"
    ).write_text(

        json.dumps(
            output,
            indent=2,
            ensure_ascii=False
        ),

        encoding="utf-8"
    )


    # --------------------------------------------------------
    # Write SVG
    # --------------------------------------------------------

    svg_content = generate_svg(

        USERNAME,

        language_percentages,

        technologies_output,

        len(repository_details),

        public_count,

        private_count,

        generated_at,

    )


    Path(
        "assets/tech-stack.svg"
    ).write_text(

        svg_content,

        encoding="utf-8"
    )


    # --------------------------------------------------------
    # Finished
    # --------------------------------------------------------

    print("")
    print("=" * 60)
    print(" DONE!")
    print("=" * 60)

    print(
        f"Repositories analyzed: "
        f"{len(repository_details)}"
    )

    print(
        f"Languages detected: "
        f"{len(language_percentages)}"
    )

    technology_count = sum(
        len(values)
        for values
        in technologies_output.values()
    )

    print(
        f"Technologies detected: "
        f"{technology_count}"
    )

    print(
        "Generated:"
    )

    print(
        "  assets/tech-stack.svg"
    )

    print(
        "  data/tech-stack.json"
    )

    print("")


if __name__ == "__main__":

    main()
