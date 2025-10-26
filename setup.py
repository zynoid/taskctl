from setuptools import setup, find_packages

setup(
    name="taskctl",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[],
    entry_points={
        'console_scripts': [
            'taskctl=taskctl:main',
            'tc=taskctl:main',
        ],
    },
    author="zynoid",
    author_email="",
    description="任务后台管理工具",
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    url="https://github.com/zynoid/taskctl",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
)