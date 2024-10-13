from setuptools import setup, find_packages

setup(
    name="vvm_to_signalk",
    version="0.1.0",
    description="An application to monitor Vessel View Mobile over Bluetooth and report to SignalK",
    author="Ryan Gregg",
    author_email="apps@ryangregg.com",
    packages=find_packages(),  # Automatically find submodules
    install_requires=[
        # List your package dependencies here
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.12',
)
