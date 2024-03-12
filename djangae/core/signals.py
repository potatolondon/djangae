from django.dispatch import Signal

# Signals will only be fired when using GAE modules, not when autoscaling
module_started = Signal()
module_stopped = Signal()
