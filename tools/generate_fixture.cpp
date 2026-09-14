#include <iostream>
#include <vector>
#include <fstream>
#include <lcf/rpg/database.h>
#include <lcf/rpg/treemap.h>
#include <lcf/rpg/map.h>
#include <lcf/ldb/reader.h>
#include <lcf/lmt/reader.h>
#include <lcf/lmu/reader.h>
#include <lcf/saveopt.h>

/**
 * Clean-Room RPG Maker 2000 Minimal Game Fixture Generator
 *
 * Deterministically creates:
 *   - RPG_RT.ini (with FullPackageFlag=0 to enforce RTP lookup)
 *   - RPG_RT.ldb (Database with Actor 1 referencing CharSet "Actor1", slot 0)
 *   - RPG_RT.lmt (Map Tree with starting location at center of Map 1)
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

    // 1. Database (RPG_RT.ldb)
    lcf::rpg::Database db;
    
    // Actor 1: References CharSet "Actor1", index 0 (top-left character in 4x2 CharSet)
    lcf::rpg::Actor actor;
    actor.ID = 1;
    actor.name = "Hero";
    actor.character_name = "Actor1";
    actor.character_index = 0;
    db.actors.push_back(actor);

    // System configuration
    db.system.party = {1};
    db.system.system_name = "System";

    // Chipset 1: Minimal chipset definition
    lcf::rpg::Chipset chipset;
    chipset.ID = 1;
    chipset.name = "Basic";
    chipset.chipset_name = "ChipSet";
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

    // Place party at center of 20x15 map (x=10, y=7)
    tree.start.party_map_id = 1;
    tree.start.party_x = 10;
    tree.start.party_y = 7;

    if (!lcf::LMT_Reader::Save(out_dir + "/RPG_RT.lmt", tree, lcf::EngineVersion::e2k)) {
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

    if (!lcf::LMU_Reader::Save(out_dir + "/Map0001.lmu", map, lcf::EngineVersion::e2k)) {
        std::cerr << "Failed to save Map0001.lmu\n";
        return 1;
    }

    // 4. INI configuration (RPG_RT.ini)
    std::ofstream ini(out_dir + "/RPG_RT.ini");
    ini << "[RPG_RT]\n";
    ini << "GameTitle=SuperRTP_Fixture\n";
    ini << "MapEditMode=2\n";
    ini << "MapEditZoom=0\n";
    ini << "FullPackageFlag=0\n"; // 0 = depends on external RTP
    ini.close();

    std::cout << "Clean-room RM2000 fixture successfully generated in " << out_dir << std::endl;
    return 0;
}
