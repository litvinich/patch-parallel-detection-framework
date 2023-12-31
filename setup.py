from setuptools import find_packages, setup


with open("requirements.txt") as file:
    requirements = file.read().splitlines()


setup(
    name="dronedet",
    description="Package for patch parallel detection",
    packages=find_packages(),
    install_requires=requirements,
    python_requires=">=3.6,<3.8",
    setup_requires=["setuptools_scm"],
    use_scm_version={"version_scheme": "python-simplified-semver"},
    include_package_data=True,
)
