"""Report module-level names (imports, assignments, defs) in each file that nothing else in the file references."""
import ast
import sys

for path in sys.argv[1:]:
    tree = ast.parse(open(path, encoding="utf-8").read())
    defined = {}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined[(alias.asname or alias.name).split(".")[0]] = node.lineno
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("test_"):
            defined[node.name] = node.lineno
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined[target.id] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    fixtures = {a.arg for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) for a in n.args.args}
    unused = sorted(name for name in defined if name not in used and name not in fixtures and name != "annotations")
    print(path, unused)
