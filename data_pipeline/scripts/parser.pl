#!/usr/bin/perl
use strict;
use warnings;
use File::Basename;
use JSON::PP;

my $script_dir  = dirname(__FILE__);
my $input_log   = "$script_dir/../storage/raw_application_log.log";
my $output_json = "$script_dir/../storage/sanitized_log.json";

print "⚡ [Perl Data Engine] Initializing regex-based text engineering pipeline...\n";

unless (-e $input_log) {
    die "🛑 [Perl Error] Missing tracking targets: $input_log does not exist.\n";
}

open(my $in_fh, '<', $input_log) or die "Can't open input file: $!";
my @records;

while (my $line = <$in_fh>) {
    chomp($line);

    if ($line =~ /^\[(.*?)\]\s+(\S+)\s+(\S+)\s+-\s+(.*)$/) {
        my $timestamp = $1;
        my $log_level = $2;
        my $component = $3;
        my $message   = $4;

        # Mask PII safely across formats
        $message =~ s/\b[A-Za-z0-9._%+-]+\@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/[REDACTED_EMAIL]/g;
        $message =~ s/Employee\s+[A-Za-z0-9_.\-]+(\s+[A-Za-z0-9_.\-]+)*/Employee [REDACTED_NAME]/gi;

        push @records, {
            timestamp => $timestamp,
            level     => $log_level,
            module    => $component,
            message   => $message
        };
    }
}
close($in_fh);

open(my $out_fh, '>', $output_json) or die "Can't open output file: $!";
my $json_encoder = JSON::PP->new->pretty(1)->canonical(1);
print $out_fh $json_encoder->encode(\@records);
close($out_fh);

my $count = scalar(@records);
print "💾 [Perl Data Engine] Parsing finalized. Saved $count records to $output_json\n";