#include <iostream>
#include <vector>
#include <fstream>
#include <lcf/rpg/database.h>
#include <lcf/rpg/treemap.h>
#include <lcf/rpg/map.h>
#include <lcf/rpg/terrain.h>
#include <lcf/ldb/reader.h>
#include <lcf/lmt/reader.h>
#include <lcf/lmu/reader.h>
#include <lcf/saveopt.h>

/**
 * Clean-Room RPG Maker 2000 Minimal Game Fixture Generator
 *
 * Deterministically creates:
 *   - RPG_RT.ini (with FullPackageFlag=0 to enforce RTP lookup)
 *   - RPG_RT.ldb (Database with Actor 1 referencing CharSet "Actor1", slot 0, and default Terrain 1)
 *   - RPG_RT.lmt (Map Tree with Root ID 0 and starting location at center of Map 1)
 *   - Map0001.lmu (20x15 tile map matching 320x240 native RM2000 screen)
 *
 * This fixture contains zero proprietary data and zero bundled CharSet assets,
 * requiring EasyRPG Player to resolve Actor1 from the external SuperRTP pack.
 */
int main(int argc, char* argv[]) {
    std::string out_dir = ".";
    if (argc > 1) {
        out_dir = argv[1];
    }
    std::string target = "rm2000";
    if (argc > 2) {
        target = argv[2];
    }
    std::string fixture_type = "charset";
    if (argc > 3) {
        fixture_type = argv[3];
    }

    bool is_2k3 = (target == "rm2003" || target == "2k3");
    bool is_chipset = (fixture_type == "chipset");
    lcf::EngineVersion version = is_2k3 ? lcf::EngineVersion::e2k3 : lcf::EngineVersion::e2k;

    // 1. Database (RPG_RT.ldb)
    lcf::rpg::Database db;
    if (is_2k3) {
        db.system.ldb_id = 2003;
    }
    
    // Actor 1
    lcf::rpg::Actor actor;
    actor.ID = 1;
    if (is_2k3) {
        actor.name = "Hero2k3";
        actor.character_name = "Hero1";
    } else {
        actor.name = "Hero";
        actor.character_name = "Actor1";
    }
    actor.character_index = 0;
    db.actors.push_back(actor);

    // Terrain 1: Standard walkable terrain (eliminates GetBushDepth invalid terrain warning)
    lcf::rpg::Terrain terrain;
    terrain.ID = 1;
    terrain.name = "Grass";
    terrain.bush_depth = 0;
    db.terrains.push_back(terrain);

    // System configuration
    db.system.party = {1};
    db.system.system_name = "System";

    // Chipset 1
    lcf::rpg::Chipset chipset;
    chipset.ID = 1;
    chipset.name = "Basic";
    if (is_chipset) {
        // Exercise engine-specific RTP alias lookup (Basis for 2k, Main for 2k3)
        if (is_2k3) {
            chipset.chipset_name = "Main";
        } else {
            chipset.chipset_name = "Basis";
        }
    } else {
        chipset.chipset_name = "ChipSet";
    }
    // Explicitly configure ChipSet terrain and passability tables
    chipset.terrain_data.assign(162, 1);        // Default all tiles to Terrain ID 1
    chipset.passable_data_lower.assign(162, 15); // Passable in all 4 directions (0x0F)
    chipset.passable_data_upper.assign(144, 15); // Upper layer passable in all 4 directions (0x0F)
    chipset.passable_data_upper[0] = 31;         // Tile 0 transparent / above-hero priority (0x1F)
    db.chipsets.push_back(chipset);

    if (!lcf::LDB_Reader::Save(out_dir + "/RPG_RT.ldb", db)) {
        std::cerr << "Failed to save RPG_RT.ldb\n";
        return 1;
    }

    // 2. Map Tree (RPG_RT.lmt)
    lcf::rpg::TreeMap tree;
    
    // Root node (ID 0)
    lcf::rpg::MapInfo root_info;
    root_info.ID = 0;
    root_info.name = "";
    root_info.type = lcf::rpg::TreeMap::MapType_root;
    tree.maps.push_back(root_info);

    // Map 1: Start map
    lcf::rpg::MapInfo mapinfo;
    mapinfo.ID = 1;
    mapinfo.name = "Map0001";
    mapinfo.type = lcf::rpg::TreeMap::MapType_map;
    mapinfo.parent_map = 0;
    tree.maps.push_back(mapinfo);
    tree.tree_order = {1};

    tree.start.party_map_id = 1;
    if (is_chipset) {
        // Place party at top-left corner (0,0) so test tiles at (2,2), (4,2), (6,2), (8,2) are unobstructed
        tree.start.party_x = 0;
        tree.start.party_y = 0;
    } else {
        // Place party at center of 20x15 map (x=10, y=7)
        tree.start.party_x = 10;
        tree.start.party_y = 7;
    }

    if (!lcf::LMT_Reader::Save(out_dir + "/RPG_RT.lmt", tree, version)) {
        std::cerr << "Failed to save RPG_RT.lmt\n";
        return 1;
    }

    // 3. Map (Map0001.lmu) - 20x15 tiles (320x240 pixels at 16x16 per tile)
    lcf::rpg::Map map;
    map.chipset_id = 1;
    map.width = 20;
    map.height = 15;
    map.lower_layer.resize(20 * 15, 0);
    map.upper_layer.resize(20 * 15, 0);

    if (is_chipset) {
        // Place fixed lower and upper tiles for verification
        // (2, 2): Tile 5000 (Block E Bank 1 lower layer)
        map.lower_layer[2 * 20 + 2] = 5000;
        // (4, 2): Tile 5096 (Block E Bank 2 lower layer)
        map.lower_layer[2 * 20 + 4] = 5096;
        // (6, 2): Tile 10048 (Block F Bank 2 upper layer)
        map.upper_layer[2 * 20 + 6] = 10048;
        // (8, 2): Tile 10000 on upper layer over Tile 5000 on lower layer (transparency & composition test)
        map.lower_layer[2 * 20 + 8] = 5000;
        map.upper_layer[2 * 20 + 8] = 10000;
    }

    if (!lcf::LMU_Reader::Save(out_dir + "/Map0001.lmu", map, version)) {
        std::cerr << "Failed to save Map0001.lmu\n";
        return 1;
    }

    // 4. INI configuration (RPG_RT.ini)
    std::ofstream ini(out_dir + "/RPG_RT.ini");
    ini << "[RPG_RT]\n";
    if (is_chipset) {
        ini << "GameTitle=" << (is_2k3 ? "SuperRTP_ChipSet_Fixture_2k3" : "SuperRTP_ChipSet_Fixture") << "\n";
    } else {
        ini << "GameTitle=" << (is_2k3 ? "SuperRTP_Fixture_2k3" : "SuperRTP_Fixture") << "\n";
    }
    ini << "MapEditMode=2\n";
    ini << "MapEditZoom=0\n";
    ini << "FullPackageFlag=0\n"; // 0 = depends on external RTP
    ini.close();

    std::cout << "Clean-room " << (is_2k3 ? "RM2003" : "RM2000") << " "
              << (is_chipset ? "chipset" : "charset")
              << " fixture successfully generated in " << out_dir << std::endl;
    return 0;
}
