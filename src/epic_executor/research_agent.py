"""Research agent for analyzing project context before implementation."""

import os
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

console = Console()


@dataclass
class ProjectContext:
    """Comprehensive project context for implementation agents."""

    # Core info
    project_root: str = ""
    project_name: str = ""

    # Language/Framework detection
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    is_typescript: bool = False
    is_monorepo: bool = False

    # Package info
    dependencies: dict[str, str] = field(default_factory=dict)
    dev_dependencies: dict[str, str] = field(default_factory=dict)

    # Conventions detected
    file_extension: str = ""  # .ts, .tsx, .js, .jsx, .py, etc.
    component_extension: str = ""  # For React: .tsx or .jsx
    naming_convention: str = ""  # kebab-case, camelCase, PascalCase
    src_directory: str = ""  # src/, app/, lib/, etc.

    # Patterns found
    existing_patterns: list[str] = field(default_factory=list)
    sample_imports: list[str] = field(default_factory=list)

    # Framework-specific
    react_version: str = ""
    next_version: str = ""
    uses_app_router: bool = False  # Next.js 13+ app router
    uses_pages_router: bool = False  # Next.js pages router
    css_solution: str = ""  # tailwind, css-modules, styled-components, etc.
    state_management: str = ""  # redux, zustand, jotai, etc.
    testing_framework: str = ""  # jest, vitest, pytest, etc.

    def to_prompt(self) -> str:
        """Convert context to a prompt section for the agent."""
        lines = ["## Project Context", ""]

        # Language
        if self.is_typescript:
            lines.append("### Language: TypeScript")
            lines.append(f"- Use `.{self.file_extension}` extension for files")
            if self.component_extension:
                lines.append(f"- Use `.{self.component_extension}` extension for React components")
            lines.append("- Include proper type annotations")
            lines.append("- NEVER use .js or .jsx extensions")
        elif self.languages:
            lines.append(f"### Languages: {', '.join(self.languages)}")

        lines.append("")

        # Frameworks
        if self.frameworks:
            lines.append(f"### Frameworks: {', '.join(self.frameworks)}")

            if "Next.js" in self.frameworks:
                if self.uses_app_router:
                    lines.append("- Using Next.js App Router (app/ directory)")
                    lines.append("- Use 'use client' directive for client components")
                elif self.uses_pages_router:
                    lines.append("- Using Next.js Pages Router (pages/ directory)")

            if "React" in self.frameworks:
                lines.append("- Use functional components with hooks")
                lines.append("- Follow React best practices")

            if "NestJS" in self.frameworks:
                lines.append("- Follow NestJS conventions (modules, services, controllers)")
                lines.append("- Use decorators for routes and dependencies")

            lines.append("")

        # CSS/Styling
        if self.css_solution:
            lines.append(f"### Styling: {self.css_solution}")
            if self.css_solution == "tailwind":
                lines.append("- Use Tailwind CSS utility classes")
            elif self.css_solution == "css-modules":
                lines.append("- Use CSS Modules (*.module.css)")
            lines.append("")

        # Source structure
        if self.src_directory:
            lines.append(f"### Source Directory: {self.src_directory}")
            lines.append(f"- Place new files under {self.src_directory}")
            lines.append("")

        # Testing
        if self.testing_framework:
            lines.append(f"### Testing: {self.testing_framework}")
            lines.append("")

        # Sample patterns
        if self.existing_patterns:
            lines.append("### Existing Code Patterns")
            for pattern in self.existing_patterns[:5]:
                lines.append(f"- {pattern}")
            lines.append("")

        # Sample imports
        if self.sample_imports:
            lines.append("### Import Style Examples")
            lines.append("```typescript")
            for imp in self.sample_imports[:5]:
                lines.append(imp)
            lines.append("```")
            lines.append("")

        return "\n".join(lines)


def analyze_package_json(project_root: str) -> dict:
    """Analyze package.json for dependencies and scripts."""
    package_path = os.path.join(project_root, "package.json")
    if not os.path.exists(package_path):
        return {}

    try:
        with open(package_path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def detect_frameworks(deps: dict) -> list[str]:
    """Detect frameworks from dependencies."""
    frameworks = []

    # Frontend
    if "next" in deps:
        frameworks.append("Next.js")
    if "react" in deps:
        frameworks.append("React")
    if "vue" in deps:
        frameworks.append("Vue.js")
    if "svelte" in deps:
        frameworks.append("Svelte")
    if "@angular/core" in deps:
        frameworks.append("Angular")

    # Backend
    if "@nestjs/core" in deps:
        frameworks.append("NestJS")
    if "express" in deps:
        frameworks.append("Express")
    if "fastify" in deps:
        frameworks.append("Fastify")
    if "hono" in deps:
        frameworks.append("Hono")

    # Full-stack
    if "remix" in deps or "@remix-run/node" in deps:
        frameworks.append("Remix")

    return frameworks


def detect_css_solution(deps: dict, project_root: str) -> str:
    """Detect CSS/styling solution."""
    if "tailwindcss" in deps:
        return "tailwind"
    if "styled-components" in deps:
        return "styled-components"
    if "@emotion/react" in deps:
        return "emotion"
    if "sass" in deps or "node-sass" in deps:
        return "sass"

    # Check for CSS modules by looking for *.module.css files
    try:
        result = subprocess.run(
            ["find", project_root, "-name", "*.module.css", "-type", "f"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.stdout.strip():
            return "css-modules"
    except Exception:
        pass

    return ""


def detect_testing_framework(deps: dict) -> str:
    """Detect testing framework."""
    if "vitest" in deps:
        return "vitest"
    if "jest" in deps:
        return "jest"
    if "@testing-library/react" in deps:
        return "react-testing-library"
    if "mocha" in deps:
        return "mocha"
    if "ava" in deps:
        return "ava"
    return ""


def detect_state_management(deps: dict) -> str:
    """Detect state management solution."""
    if "zustand" in deps:
        return "zustand"
    if "jotai" in deps:
        return "jotai"
    if "@reduxjs/toolkit" in deps or "redux" in deps:
        return "redux"
    if "recoil" in deps:
        return "recoil"
    if "mobx" in deps:
        return "mobx"
    return ""


def detect_next_router(project_root: str) -> tuple[bool, bool]:
    """Detect which Next.js router is in use."""
    app_dir = os.path.exists(os.path.join(project_root, "app"))
    src_app_dir = os.path.exists(os.path.join(project_root, "src", "app"))
    pages_dir = os.path.exists(os.path.join(project_root, "pages"))
    src_pages_dir = os.path.exists(os.path.join(project_root, "src", "pages"))

    uses_app = app_dir or src_app_dir
    uses_pages = pages_dir or src_pages_dir

    return uses_app, uses_pages


def detect_src_directory(project_root: str) -> str:
    """Detect the main source directory."""
    candidates = ["src", "app", "lib", "source"]
    for candidate in candidates:
        if os.path.isdir(os.path.join(project_root, candidate)):
            return candidate
    return ""


def sample_existing_code(project_root: str, extension: str) -> tuple[list[str], list[str]]:
    """Sample existing code to detect patterns and import styles."""
    patterns = []
    imports = []

    try:
        # Find some source files
        result = subprocess.run(
            ["find", project_root, "-name", f"*.{extension}", "-type", "f",
             "-not", "-path", "*/node_modules/*",
             "-not", "-path", "*/.next/*",
             "-not", "-path", "*/dist/*"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        files = result.stdout.strip().split("\n")[:10]  # Sample up to 10 files

        for file_path in files:
            if not file_path:
                continue
            try:
                with open(file_path, "r") as f:
                    content = f.read()

                # Extract import statements
                for line in content.split("\n")[:30]:  # First 30 lines
                    if line.startswith("import "):
                        if line not in imports:
                            imports.append(line)
                            if len(imports) >= 10:
                                break

                # Detect patterns
                if "export default function" in content:
                    patterns.append("Uses default function exports")
                if "export const" in content:
                    patterns.append("Uses named const exports")
                if "'use client'" in content:
                    patterns.append("Uses 'use client' directive (Next.js client components)")
                if "interface " in content or "type " in content:
                    patterns.append("Uses TypeScript interfaces/types")

            except Exception:
                continue

    except Exception:
        pass

    # Deduplicate patterns
    patterns = list(set(patterns))

    return patterns, imports


def analyze_project(project_root: str) -> ProjectContext:
    """Perform comprehensive project analysis."""
    console.print(f"[dim]Analyzing project: {project_root}[/dim]")

    ctx = ProjectContext(project_root=project_root)
    ctx.project_name = os.path.basename(project_root)

    # Check for TypeScript
    if os.path.exists(os.path.join(project_root, "tsconfig.json")):
        ctx.is_typescript = True
        ctx.languages.append("TypeScript")
        ctx.file_extension = "ts"
        ctx.component_extension = "tsx"
    else:
        ctx.languages.append("JavaScript")
        ctx.file_extension = "js"
        ctx.component_extension = "jsx"

    # Analyze package.json
    pkg = analyze_package_json(project_root)
    if pkg:
        ctx.project_name = pkg.get("name", ctx.project_name)
        ctx.dependencies = pkg.get("dependencies", {})
        ctx.dev_dependencies = pkg.get("devDependencies", {})

        all_deps = {**ctx.dependencies, **ctx.dev_dependencies}

        # Detect frameworks
        ctx.frameworks = detect_frameworks(all_deps)

        # Detect versions
        ctx.react_version = all_deps.get("react", "")
        ctx.next_version = all_deps.get("next", "")

        # Detect CSS solution
        ctx.css_solution = detect_css_solution(all_deps, project_root)

        # Detect testing
        ctx.testing_framework = detect_testing_framework(all_deps)

        # Detect state management
        ctx.state_management = detect_state_management(all_deps)

    # Detect Next.js router type
    if "Next.js" in ctx.frameworks:
        ctx.uses_app_router, ctx.uses_pages_router = detect_next_router(project_root)

    # Detect source directory
    ctx.src_directory = detect_src_directory(project_root)

    # Sample existing code
    ext = ctx.component_extension if ctx.component_extension else ctx.file_extension
    ctx.existing_patterns, ctx.sample_imports = sample_existing_code(project_root, ext)

    # Check for monorepo
    if os.path.exists(os.path.join(project_root, "packages")) or \
       os.path.exists(os.path.join(project_root, "apps")):
        ctx.is_monorepo = True

    console.print(f"[dim]  Detected: {', '.join(ctx.frameworks) if ctx.frameworks else 'No frameworks'}[/dim]")
    console.print(f"[dim]  TypeScript: {ctx.is_typescript}[/dim]")

    return ctx


def get_project_context_prompt(project_root: str) -> str:
    """Get the project context formatted as a prompt section."""
    ctx = analyze_project(project_root)
    return ctx.to_prompt()
