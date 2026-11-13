__all__ = ["JarvisUI", "MainWindow"]


def __getattr__(name):
    if name in __all__:
        from ui import window
        return getattr(window, name)
    raise AttributeError(name)

# by ASDcuber521
