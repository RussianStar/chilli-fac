from abc import ABC, abstractmethod

class gpio_device(ABC):
    @abstractmethod
    def cleanup_gpio(self, arg1):
        """Abstract method one."""
        pass

