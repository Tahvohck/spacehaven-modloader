import math
import os
from typing import List, Dict

import lxml.etree
import png
import rectpack


class RegisteredTexture:
    """All the metadata needed to construct a region node."""
    ParentMod: str
    TexPath: str
    CoreRegionID: int
    FileSizeX: int
    FileSizeY: int

    def __init__(self, mod: str, texPath: str, regionID: int):
        self.ParentMod = mod
        self.TexPath = texPath
        self.CoreRegionID = regionID

        filepath = TextureManager.getModTexturePath(self.ParentMod, self.TexPath)
        (w, h, rows, info) = png.Reader(filepath).asRGBA()

        self.FileSizeX = w
        self.FileSizeY = h

    def __str__(self):
        return f"[{self.CoreRegionID:0>5}] {self.ParentMod}: {self.TexPath} - ({self.FileSizeX}, {self.FileSizeY})"


RegTexLibrary = List[RegisteredTexture]


class TextureManager:
    _TexFileResolution = 2000
    _RegionIdLastCore = 0
    _RegionIdNextOffset = 1
    _logger = None

    RegisteredTexturesCustomRegion : RegTexLibrary = []
    RegisteredTexturesCoreRegion : RegTexLibrary = []
    RegisteredModPaths : Dict[str, str] = dict()
    RemappedRegionIDs : Dict[object, int] = dict()
    CustomTextureIDStart = 400

    Packer : rectpack.PackerGlobal = None

    @classmethod
    def setup(cls, lastCoreRegionID: int, loggerMethod):
        cls._RegionIdLastCore = lastCoreRegionID
        cls._RegionIdNextOffset = 1
        cls._logger = loggerMethod

        # Reset registries
        cls.RegisteredTexturesCustomRegion : RegTexLibrary = []
        cls.RegisteredTexturesCoreRegion : RegTexLibrary = []
        cls.RegisteredModPaths : Dict[str, str] = dict()
        cls.RemappedRegionIDs : Dict[object, int] = dict()
        cls.log(f"Done setup: core region ends at {cls._RegionIdLastCore}")

    @classmethod
    def registerNewTexture(cls, mod: str, texPath: str, regionID: int = -1):
        """
        Register a new texture to be managed. Region ID must NOT be -1 during normal
        operation, this is for debugging only. Core region textures will be stored
        as-is, custom textures will have their region ID remapped to the next available
        sequential region ID.
        """
        if not cls.customTextureExists(mod, texPath):
            modName = os.path.basename(os.path.realpath(mod))
            raise ValueError(f"Could not register {texPath}, file does not exist. Mod: {modName}")

        if cls.isCoreRegion(regionID):
            tmp = RegisteredTexture(mod, texPath, regionID)
            cls.RegisteredTexturesCoreRegion.append(tmp)
        else:
            if regionID != -1 and regionID in cls.RemappedRegionIDs:
                raise KeyError(f"Cannot remap ID {regionID}: Already remapped!")
            rid = cls.popNextRegionID()
            tmp = RegisteredTexture(mod, texPath, rid)
            cls.RegisteredTexturesCustomRegion.append(tmp)
            cls.RemappedRegionIDs[regionID] = rid

    @classmethod
    def pack(cls):
        packer = rectpack.newPacker(rotation=False)
        cls.Packer = packer

        # as many bins as needed
        packer.add_bin(cls._TexFileResolution, cls._TexFileResolution, float("inf"))

        for rt in cls.RegisteredTexturesCustomRegion:
            rt: RegisteredTexture
            packer.add_rect(rt.FileSizeX, rt.FileSizeY, cls.RegisteredTexturesCustomRegion.index(rt))

        packer.pack()

    @classmethod
    def log(cls, *values):
        if cls._logger:
            cls._logger(*values)

    @classmethod
    def popNextRegionID(cls):
        """Get next region ID and increment the counter"""
        tmp = cls._RegionIdLastCore + cls._RegionIdNextOffset
        cls._RegionIdNextOffset += 1
        return tmp

    @classmethod
    def isCoreRegion(cls, rID: int):
        """
        Check if a given regionID number is inside the game's "core" set of
        region IDs.
        """
        try:
            rID = int(rID)
            return rID > -1 and rID <= cls._RegionIdLastCore
        except ValueError:
            return False

    @classmethod
    def customTextureExists(cls, mod, texPath):
        """
        Verify whether or not a RegisteredTexture can be created, i.e. if the file exists in the mod's textures/ folder
        """
        try:
            RegisteredTexture(mod, texPath, -1)
            return True
        except FileNotFoundError as e:
            return False

    @classmethod
    def getModTexturePath(cls, mod: str, texPath: str):
        """Get the correct locaton for a given texture sub-path and mod combination."""
        if mod not in cls.RegisteredModPaths:
            texFolderPath = os.path.join(mod, "textures")
            if os.path.exists(texFolderPath):
                cls.RegisteredModPaths[mod] = texFolderPath
            else:
                raise FileNotFoundError(f"Couldn't find {texFolderPath}")
        return os.path.join(cls.RegisteredModPaths[mod], texPath)

    @classmethod
    def getXMLTexture(cls):
        """
        Build the lxml ElementTree that defines the current set of custom textures
        ONLY. Although core region overrides can be registered, they will NEVER be
        included in the output from this function.
        """
        texRoot = lxml.etree.Element("AllTexturesAndRegions")
        lxml.etree.SubElement(texRoot, "textures")
        lxml.etree.SubElement(texRoot, "regions")
        texTree = lxml.etree.ElementTree(texRoot)
        regionsNode = texTree.find("//regions")
        texturesNode = texTree.find("//textures")

        packedRectsSorted = {}
        for rect in cls.Packer.rect_list():
            b, x, y, w, h, regModTexIDX = rect
            regionID = cls.RegisteredTexturesCustomRegion[regModTexIDX].CoreRegionID
            packedRectsSorted[regionID] = (b, str(x), str(y), str(w), str(h), regModTexIDX)
        # NOT YET SORTED
        packedRectsSorted = {k: v for k,v in sorted(packedRectsSorted.items())}
        # NOW SORTED
        binIndexes = set()

        for regionID, rect in packedRectsSorted.items():
            newNode = lxml.etree.SubElement(regionsNode, "re")

            rt: RegisteredTexture; rt = cls.RegisteredTexturesCustomRegion[regModTexIDX]
            regionFileName = cls.getModTexturePath(rt.ParentMod, rt.TexPath)
            bin, x, y, w, h, regModTexIDX = rect
            binIndexes.add(bin)

            newNode.set("n", str(regionID))
            newNode.set("t", str(cls.getBinTextureID(bin)))
            newNode.set("x", x)
            newNode.set("y", y)
            newNode.set("w", w)
            newNode.set("h", h)
            newNode.set("file", regionFileName)

        for bin in binIndexes:
            newTex = lxml.etree.SubElement(texturesNode, "t")
            newTex.set("i", str(cls.getBinTextureID(bin)))
            newTex.set("w", str(cls._TexFileResolution))
            newTex.set("h", str(cls._TexFileResolution))

        return texTree

    @classmethod
    def getBinTextureID(cls, bin: int):
        """Get the texture ID for for a given bin index."""
        return cls.CustomTextureIDStart + bin

    @classmethod
    def getRegionIDMapping(cls, rid: int):
        if cls.isCoreRegion(rid):
            return rid
        else:
            return cls.RemappedRegionIDs[rid]


if __name__ == "__main__":
    """Run some basic unit tests."""
    TextureManager.setup(10, print)

    testFileDir = "unit-tests/textures"
    for filename in os.listdir(testFileDir):
        repeat = os.stat(os.path.join(testFileDir, filename)).st_size
        # magic numbers chosen semi-randomly to get a good spread of repeats
        repeat = math.ceil((210 - repeat)/ 9) ** 2
        print(f"{filename:>11} - {repeat:>2}")
        for x in range(repeat):
            TextureManager.registerNewTexture("unit-tests", filename)

    TextureManager.pack()
    with open("unit-tests/textures-output.xml", 'wb') as f:
        f.write(lxml.etree.tostring(TextureManager.getXMLTexture(), pretty_print=True))

    for bin in TextureManager.Packer:
        r1str = f"x{bin[ 0].x}, y{bin[ 0].y} ({bin[ 0].rid})"
        r2str = f"x{bin[-1].x}, y{bin[-1].y} ({bin[-1].rid})"
        binstr = f"{len(bin):>3} rects, first {r1str}, last {r2str}"
        print(binstr)
    numBins = len(TextureManager.Packer)
    numRects = len(TextureManager.Packer.rect_list())
    numRectsRaw = len(TextureManager.RegisteredTexturesCustomRegion)
    print(f"{numBins} bins, {numRects} rects ({numRectsRaw} raw)")

    for filename in os.listdir(testFileDir):
        try:
            TextureManager.registerNewTexture("unit-tests", filename, 20)
        except KeyError as e:
            print(f"Caught KeyError as expected: {e.args[0]}")
            break

    print(f"Remap check: 20 -> {TextureManager.getRegionIDMapping(20)}")

    print("CTM compiles.")
