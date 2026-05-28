if __name__ == "__main__":
    import runpy
    runpy.run_module("tools.search_expanded_registry", run_name="__main__")
else:
    from tools.search_expanded_registry import *  # noqa: F401,F403
