#!/usr/bin/python
from setuptools import setup

setup(
    setup_requires=[
        'pbr >= 1.9',
        'setuptools >= 17.1'
    ],
    pbr=True,
    packages=['dirdelta'],
    entry_points={
        'console_scripts': ['dirdelta=dirdelta.main:main']
    }
)
