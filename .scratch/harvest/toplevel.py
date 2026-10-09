"""Print the top-level names a Python test file defines or imports, one per line, with line numbers."""
import ast
import sys

for path in sys.argv[1:]:
    print(f"== {path}")
    tree = ast.parse(open(path).read())
    for node in tree.body:
        names = []
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names += [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names += [a.asname or a.name for a in node.names]
        for name in names:
            print(f"{node.lineno}\t{name}")
