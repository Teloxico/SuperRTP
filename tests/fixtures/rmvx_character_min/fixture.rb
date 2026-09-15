# SuperRTP Clean-Room RGSS2 Character Test Harness
# Target: RPG Maker VX (RGSS2)
# Verifies character bitmap loading, dimensions, 8-character sheet layout, and transparent rendering.

puts "MKXP-Z VERSION: #{System::VERSION}"

# Assert RGSS2 default screen dimensions: 544x416
unless Graphics.width == 544 && Graphics.height == 416
  $stderr.puts "SUPERRTP_RGSS2_SCREEN_ERROR: Expected 544x416, got #{Graphics.width}x#{Graphics.height}"
  Process.exit!(3)
end
puts "SUPERRTP_RGSS2_SCREEN 544x416"

# Setup 544x416 scene with high-contrast background to verify sprite rendering and transparency
bg = Sprite.new
bg.bitmap = Bitmap.new(544, 416)
# Neutral dark background
bg.bitmap.fill_rect(0, 0, 544, 416, Color.new(25, 25, 30, 255))

# Contrasting test pad centered under character sheet
# Standard 8-character sheet is 288x256, placed at x=128, y=80 (margin 128 left/right, 80 top/bottom)
# Test pad size: 312x280 placed at x=116, y=68 (12px padding around sheet)
bg.bitmap.fill_rect(116, 68, 312, 280, Color.new(210, 215, 220, 255))

# Corner alignment marks on pad (8x8 squares)
bg.bitmap.fill_rect(116, 68, 8, 8, Color.new(255, 60, 60, 255))      # TL Red
bg.bitmap.fill_rect(420, 68, 8, 8, Color.new(60, 255, 60, 255))      # TR Green
bg.bitmap.fill_rect(116, 340, 8, 8, Color.new(60, 60, 255, 255))     # BL Blue
bg.bitmap.fill_rect(420, 340, 8, 8, Color.new(255, 255, 60, 255))    # BR Yellow

begin
  # Load via RTP lookup with omitted extension
  char_bmp = Bitmap.new("Graphics/Characters/Actor1")
  puts "SUPERRTP_RMVX_CHARACTER_LOADED #{char_bmp.width}x#{char_bmp.height}"

  unless char_bmp.width == 288 && char_bmp.height == 256
    $stderr.puts "SUPERRTP_RMVX_DIMENSION_ERROR: Expected 288x256, got #{char_bmp.width}x#{char_bmp.height}"
    Process.exit!(4)
  end

  # Character Sprite displaying the entire 288x256 sheet at native 1:1 scale
  char_sprite = Sprite.new
  char_sprite.bitmap = char_bmp
  char_sprite.x = 128
  char_sprite.y = 80

  # Update Graphics for 60 frames (~1 second) to allow lossless capture
  60.times do
    Graphics.update
  end

  puts "SUPERRTP_RMVX_RENDER_DONE"
  exit 0

rescue Errno::ENOENT => e
  $stderr.puts "SUPERRTP_RMVX_MISSING_ASSET: #{e.message}"
  # Update Graphics for 30 frames to allow negative control capture of the blank pad
  30.times do
    Graphics.update
  end
  Process.exit!(1)
rescue => e
  $stderr.puts "SUPERRTP_RMVX_ERROR: #{e.class}: #{e.message}"
  Process.exit!(2)
end
