import ast
import os
import sys

ROOT_PATH = os.path.dirname(__file__)

class ImportAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.required_imports = set()
        self.optional_imports = set()
        self.current_try_depth = 0

    def visit_Import(self, node):
        for alias in node.names:
            if self.current_try_depth > 0:
                self.optional_imports.add(alias.name.split('.')[0])
            else:
                self.required_imports.add(alias.name.split('.')[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module
        if module and not module.startswith('anylog_'):
            if self.current_try_depth > 0:
                self.optional_imports.add(module.split('.')[0])
            else:
                self.required_imports.add(module.split('.')[0])
        self.generic_visit(node)

    def visit_Try(self, node):
        self.current_try_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        self.current_try_depth -= 1
        for handler in node.handlers:
            self.visit(handler)
        for stmt in node.orelse:
            self.visit(stmt)
        for stmt in node.finalbody:
            self.visit(stmt)


def analyze_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    analyzer = ImportAnalyzer()
    analyzer.visit(tree)
    return analyzer.required_imports, analyzer.optional_imports


def main():
    all_required = set()
    all_optional = set()
    filenames = set()

    for dirname in ['CLI']:
        path = os.path.join(ROOT_PATH, dirname)
        for root, _, files in os.walk(path):
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    filenames.update(file.split(".py")[0])
                    try:
                        required, optional = analyze_file(full_path)
                        all_required.update(required)
                        all_optional.update(optional)
                    except Exception as e:
                        print(f"Error processing {full_path}: {e}", file=sys.stderr)

        # Remove overlaps (required takes precedence)
        truly_optional = all_optional - all_required

        print("Required packages:")
        for pkg in sorted(all_required):
            if pkg not in filenames:
                print(f"  {pkg}")

        print("\nOptional (try/except) packages:")
        for pkg in sorted(truly_optional):
            if pkg not in filenames:
                print(f"  {pkg}")
            # print(f"  {pkg}")


if __name__ == "__main__":
    main()
