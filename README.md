# Doompatcher

Adds Doctor Doom as a 19th playable character to Marvel Nemesis: Rise of the Imperfects (GameCube, USA).

<b>This repo does not include any game files.</b>

Doom has a custom model, uses Johnny Ohm's moveset (but does not replace him), and has his own in-game UI assets.

[![Doompatcher demo video](https://img.youtube.com/vi/W564qL8WLl8/maxresdefault.jpg)](https://youtu.be/W564qL8WLl8)

## What you need

- Your own copy of the game: USA release, game ID `GVLE69`, as an `.iso` or `.ciso`. <b>No game files are included here.</b>
- Python 3.8 or newer, with Pillow: `pip install pillow`
- About 3 GB of free disk space.

## Usage

    python3 doompatcher.py "Nemesis.iso"

This writes `Marvel Nemesis (Doctor Doom).iso` next to the original. A second argument picks another output path. Tested in Dolphin.

## Credits

- **Doctor Doom model**: "19 Dr. Doom MUA" by [ak2yny](https://sketchfab.com/ak2yny), from [Sketchfab](https://sketchfab.com/3d-models/19-dr-doom-mua-c82f86e921a742c0903db5e81e8f9497), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
  - Changes: textures were modified to match the desired look for Doom.
- **UI art** (select-screen portrait, tile, loading screen and HUD icons): the Doctor Doom artwork is
  originally by comic book artist **Jae Lee**, the original artist for Marvel Nemesis. Rights to the original art belong to him.
  - Changes: I modified the art (cropping, recoloring and resizing) to fit Marvel Nemesis.
- The [mnroi decomp project](https://github.com/Esoteric-Engineer/mnroi).

## License

- **Code**: [MIT](LICENSE.md).
- **Textures** (`assets/model/`): [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).
- **UI art** (the other `assets/` images): my modifications only; the underlying artwork is Jae Lee's and is not covered by any license here.
- **Doom model** (`assets/doom_mua.glb`): CC BY 4.0, by ak2yny (see Credits).

This is a fan project, not affiliated with or endorsed by Marvel, Electronic Arts or Nintendo.