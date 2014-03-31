from setuptools import setup, find_packages

setup(
    name='il2ds-mis-parser',
    version='1.0.0',
    description='Parse IL-2 DS mission file and produce detailed information about mission.',
    license='BSD License',
    url='https://github.com/IL2HorusTeam/il2ds-mis-parser',
    author='Alexander Oblovatniy, Alexander Kamyhin',
    author_email='oblovatniy@gmail.com, kamyhin@gmail.com',
    packages=find_packages(),
    install_requires=[i.strip() for i in open("requirements.pip").readlines()],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'License :: Free for non-commercial use',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2.7',
        'Topic :: Software Development :: Libraries',
    ],
)