from setuptools import setup, find_packages

long_description = 'Performance monitoring CLI tool for Apple Silicon'

setup(
    name='mactop',
    version='0.1',
    author='Jinyu Chen',
    author_email='visualcjy@mail.com',
    url='https://github.com/visualcjy/mactop',
    description='Performance monitoring CLI tool for Apple Silicon',
    long_description=long_description,
    long_description_content_type="text/markdown",
    license='MIT',
    packages=find_packages(),
    entry_points={
            'console_scripts': [
                'mactop = mactop.mactop:main'
            ]
    },
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: MacOS",
    ),
    keywords='mactop',
    install_requires=[
        "dashing",
        "psutil",
        "humanize",
    ],
    zip_safe=False
)
