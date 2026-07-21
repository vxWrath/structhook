from functools import wraps


def force_classmethod(func):
    @wraps(func)
    def wrapper(cls, *args, **kwargs):
        # Your custom logic here
        return func(cls, *args, **kwargs)
    
    # Wrap the wrapper in the built-in classmethod descriptor
    return classmethod(wrapper)

class MyClass:
    class_variable = "Hello from Class"

    @force_classmethod
    @classmethod
    def my_method(cls, extra_text):
        return f"{cls.class_variable} - {extra_text}"

# Call directly on the class
print(MyClass.my_method("It works!")) 
# Output: Hello from Class - It works!
