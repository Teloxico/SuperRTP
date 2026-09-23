# SuperRTP clean-room RGSS pack scan (RGSS1/2/3 under mkxp-z).
# tools/verify_generated_packs.py copies this script next to a scan_list.txt:
#   line 1:   "<screen width> <screen height>"
#   then one image path per line, without extension ("Graphics/Titles/Book");
#   a leading "*" also draws the image as a thumbnail on the contact sheet.
# Every image is loaded through the RTP search path. Results go to stderr, which is
# unbuffered, so they survive any exit.

lines = File.readlines("scan_list.txt").map { |l| l.chomp }.reject { |l| l.empty? }
screen_w, screen_h = lines.shift.split.map { |v| v.to_i }
loaded = 0
failed = 0
thumbs = []

lines.each do |line|
  thumb = line.start_with?("*")
  path = thumb ? line[1..-1] : line
  begin
    bmp = Bitmap.new(path)
    $stderr.puts "SUPERRTP_SCAN #{path} #{bmp.width}x#{bmp.height}"
    loaded += 1
    if thumb
      thumbs << bmp
    else
      bmp.dispose
    end
  rescue Exception => e
    $stderr.puts "SUPERRTP_SCAN_ERROR #{path}: #{e.class}: #{e.message}"
    failed += 1
  end
end

# Contact sheet: 8 x 6 cells on a dark background, magenta corner markers so the harness
# can tell the finished sheet from start-up frames.
magenta = Color.new(255, 0, 255, 255)
back = Sprite.new
back.bitmap = Bitmap.new(screen_w, screen_h)
back.bitmap.fill_rect(0, 0, screen_w, screen_h, Color.new(30, 30, 36, 255))
cols, rows = 8, 6
cw, ch = screen_w / cols, screen_h / rows
thumbs.first(cols * rows).each_with_index do |bmp, i|
  x, y = (i % cols) * cw, (i / cols) * ch
  scale = [(cw - 4).to_f / bmp.width, (ch - 4).to_f / bmp.height].min
  w, h = [(bmp.width * scale).to_i, 1].max, [(bmp.height * scale).to_i, 1].max
  back.bitmap.stretch_blt(Rect.new(x + (cw - w) / 2, y + (ch - h) / 2, w, h), bmp, bmp.rect)
end
[[0, 0], [screen_w - 4, 0], [0, screen_h - 4], [screen_w - 4, screen_h - 4]].each do |mx, my|
  back.bitmap.fill_rect(mx, my, 4, 4, magenta)
end

240.times { Graphics.update }
$stderr.puts "SUPERRTP_SCAN_DONE loaded=#{loaded} failed=#{failed}"
exit 0
