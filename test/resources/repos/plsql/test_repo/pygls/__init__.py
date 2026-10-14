# A project module named like a dependency of the PL/SQL language server: the server must not import it from the
# project directory (in which it runs).
raise ImportError("the PL/SQL language server imported a module from the analysed project")
