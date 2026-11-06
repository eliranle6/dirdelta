#!/usr/bin/python
from setuptools import find_packages, setup

setup(
    setup_requires=[
        'pbr >= 1.9',
        'setuptools >= 17.1'
    ],
    pbr=True,
    packages=find_packages(include=['dirdelta', 'dirdelta.*']),
    entry_points={
        'console_scripts': ['dirdelta=dirdelta.main:main']
    }
)
