def test_pipeline_does_not_import_twilio():
    import ast, pathlib
    src = pathlib.Path("app/pipeline.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in getattr(node, "names", [])]
            module = getattr(node, "module", "") or ""
            assert "twilio" not in module.lower(), "pipeline.py still imports twilio"
            for n in names:
                assert "twilio" not in n.lower()
