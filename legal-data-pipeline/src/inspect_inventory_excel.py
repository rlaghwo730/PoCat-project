if __name__ == "__main__":
    import runpy
    runpy.run_module("tools.inspect_inventory_excel", run_name="__main__")
else:
    from tools.inspect_inventory_excel import *  # noqa: F401,F403
