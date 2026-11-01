class HoverAnimationMixin:
    def _set_h(self, value):
        self._h = float(value)
        self.update()
    def _go(self, target):
        self._an.stop()
        self._an.setStartValue(self._h)
        self._an.setEndValue(target)
        self._an.start()
    def enterEvent(self, event):
        self._go(1.0)
        super().enterEvent(event)
    def leaveEvent(self, event):
        self._go(0.0)
        super().leaveEvent(event)

#by ASDcuber
