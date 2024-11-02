from setuptools import setup, find_packages

long_description = 'Performance monitoring CLI tool for Apple Silicon'

setup(
    name='macpm',
    version='0.12',
    author='Jinyu Chen',
    author_email='visualcjy@mail.com',
    url='https://github.com/visualcjy/macpm',
    description='Performance monitoring CLI tool for Apple Silicon',
    long_description=long_description,
    long_description_content_type="text/markdown",
    license='MIT',
    packages=find_packages(),
    package_dir={'macpm':'macpm'},
    entry_points={
            'console_scripts': [
                'macpm = macpm.macpm:main'
            ]
    },
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: MacOS",
    ),
    keywords='macpm',
    install_requires=[
        "dashing",
        "psutil",
        "humanize",
    ],
    zip_safe=False
)
