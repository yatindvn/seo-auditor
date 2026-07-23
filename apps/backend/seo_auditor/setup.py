from setuptools import setup, find_packages

setup(
    name="seo-auditor",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31",
        "beautifulsoup4>=4.12",
        "lxml>=5.0",
        "openpyxl>=3.1",
        "reportlab>=4.0",
        "networkx>=3.0",
    ],
    entry_points={
        "console_scripts": [
            "seo-audit=seo_auditor.cli:main",
        ],
    },
    python_requires=">=3.8",
)
