# SuperRTP Clean-Room RGSS1 Character Test Harness
# Target: RPG Maker XP (RGSS1)
# Verifies character bitmap loading, dimensions, directional layout, and transparent rendering.

puts "MKXP-Z VERSION: #{System::VERSION}"

# Setup 640x480 scene with high-contrast background to verify sprite rendering and transparency
bg = Sprite.new
bg.bitmap = Bitmap.new(640, 480)
# Neutral dark background
bg.bitmap.fill_rect(0, 0, 640, 480, Color.new(25, 25, 30, 255))
# Contrasting test pad centered under character sheet (sheet is 96x128, place at x=272, y=176)
bg.bitmap.fill_rect(260, 164, 120, 152, Color.new(210, 215, 220, 255))
# Corner alignment marks on pad
bg.bitmap.fill_rect(260, 164, 8, 8, Color.new(255, 60, 60, 255))
bg.bitmap.fill_rect(372, 164, 8, 8, Color.new(60, 255, 60, 255))
bg.bitmap.fill_rect(260, 308, 8, 8, Color.new(60, 60, 255, 255))
bg.bitmap.fill_rect(372, 308, 8, 8, Color.new(255, 255, 60, 255))

begin
  char_bmp = Bitmap.new("Graphics/Characters/001-Fighter01")
  puts "SUPERRTP_RMXP_CHARACTER_LOADED #{char_bmp.width}x#{char_bmp.height}"

  # Character Sprite displaying the entire 96x128 sheet
  char_sprite = Sprite.new
  char_sprite.bitmap = char_bmp
  char_sprite.x = 272
  char_sprite.y = 176

  # Update Graphics for 60 frames (~1 second) to allow lossless capture
  60.times do
    Graphics.update
  end

  puts "SUPERRTP_RMXP_RENDER_DONE"
  exit 0

rescue Errno::ENOENT => e
  $stderr.puts "SUPERRTP_RMXP_MISSING_ASSET: #{e.message}"
  # Update Graphics for 30 frames to allow negative control capture of the blank pad
  30.times do
    Graphics.update
  end
  Process.exit!(1)
rescue => e
  $stderr.puts "SUPERRTP_RMXP_ERROR: #{e.class}: #{e.message}"
  Process.exit!(2)
end
