if __name__ == "__main__":
    import runpy
    runpy.run_module("tools.check_legal_documents", run_name="__main__")
else:
    from tools.check_legal_documents import *  # noqa: F401,F403
