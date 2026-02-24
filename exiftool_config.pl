# ExifTool config: register Apple's XMP namespace for Live Photo pairing
# Used by: convert.py via  exiftool -config exiftool_config.pl

%Image::ExifTool::UserDefined = (
    'Image::ExifTool::XMP::Main' => {
        'apple-fi' => {
            SubDirectory => {
                TagTable => 'Image::ExifTool::UserDefined::apple_fi',
            },
        },
    },
);

%Image::ExifTool::UserDefined::apple_fi = (
    GROUPS    => { 0 => 'XMP', 1 => 'XMP-apple-fi', 2 => 'Image' },
    NAMESPACE => { 'apple-fi' => 'http://ns.apple.com/faceinfo/1.0/' },
    WRITABLE  => 'string',
    ContentIdentifier => { },
);

1;
