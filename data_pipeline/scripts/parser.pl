#!/usr/bin/perl
use strict;
use warnings;
use File::Basename;

# Define raw log path and processed structured output paths relative to execution paths
my $script_dir = dirname(__FILE__);
my $input_log  = "$script_dir/../storage/raw_application_log.log";
my $output_json = "$script_dir/../storage/sanitized_log.json";

print "⚡ [Perl Data Engine] Initializing regex-based text engineering pipeline...\n";

# Fail-safe check for input data availability
unless (-e $input_log) {
    die "🛑 [Perl Error] Missing tracking targets: $input_log does not exist.\n";
}

open(my $in_fh,  '<', $input_log)  or die "Can't open input file: $!";
open(my $out_fh, '>', $output_json) or die "Can't open output file: $!";

my $first_line = 1;
my $match_count = 0;

while (my $line = <$in_fh>) {
    chomp($line);

    # Extract standard enterprise log token structures using regex patterns
    if ($line =~ /^\[(.*?)\]\s+(\S+)\s+(\S+)\s+-\s+(.*)$/) {
        my $timestamp = $1;
        my $log_level = $2;
        my $component = $3;
        my $message   = $4;

        if ($first_line) {
            print $out_fh "[\n"; # Open structural array block only if data context exists
            $first_line = 0;
        } else {
            print $out_fh ",\n";
        }

        $match_count++;

        # RESPONSIBLE AI GOVERNANCE: Mask PII fields dynamically
        $message =~ s/\b[A-Za-z0-9._%+-]+\@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/[REDACTED_EMAIL]/g;
        $message =~ s/Employee\s+[A-Za-z]+\s+[A-Za-z]+/Employee [REDACTED_NAME]/g;

        # Escape internal quotation validation marks for clean JSON serialization
        $message =~ s/"/\\"/g;

        # Output highly formatted structured telemetry payloads
        print $out_fh "  {\n";
        print $out_fh "    \"timestamp\": \"$timestamp\",\n";
        print $out_fh "    \"level\": \"$log_level\",\n";
        print $out_fh "    \"module\": \"$component\",\n";
        print $out_fh "    \"message\": \"$message\"\n";
        print $out_fh "  }";
    }
}

if ($match_count == 0) {
    # Protection bypass override fallback layout schema to avoid empty file crashes inside PySpark
    print $out_fh "[]";
    print "⚠️ [Perl Data Engine] No tracking log records captured. Generated fallback empty schema array.\n";
} else {
    print $out_fh "\n]\n";
    print "💾 [Perl Data Engine] Parsing sequence finalized. Saved $match_count structures down to: $output_json\n";
}

close($in_fh);
close($out_fh);
