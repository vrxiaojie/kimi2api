from setuptools import setup, find_packages

with open("requirements.txt", encoding="utf-8") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="kimi2api",
    version="1.0.0",
    description="Kimi Web Chat to OpenAI-Compatible API Proxy",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="kimi2api",
    python_requires=">=3.9",
    packages=find_packages(),
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "kimi2api=kimi2api.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
