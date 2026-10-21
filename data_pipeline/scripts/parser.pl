#!/usr/bin/env perl
# Parse raw application logs into JSON Lines and redact structured PII.
#
#   perl parser.pl [--out sanitized.jsonl] [--rejects rejects.log] [--stats stats.json] raw.log ...
#
# Stage 1 of the log pipeline. Perl handles the fast, deterministic part: structural parsing and
# regex redaction of identifiers with a fixed shape: emails (incl. "(at)/[dot]" spellings), phones,
# SSNs, card numbers (15-19 digits + issuer prefix + Luhn), IPv4 addresses, API keys and
# "Employee <username>". Person names cannot be found reliably with regex; they are redacted by
# the spaCy NER step in the Spark job (stage 2).
#
# Lines that do not match the log format are written to the rejects file and counted, never
# silently dropped. Exit code 2 means the input could not be read.
use strict;
use warnings;
use Getopt::Long;
use JSON::PP;

my ($out_path, $rejects_path, $stats_path) = ("-", undef, undef);
GetOptions("out=s" => \$out_path, "rejects=s" => \$rejects_path, "stats=s" => \$stats_path)
    or die "usage: $0 [--out F] [--rejects F] [--stats F] input...\n";
@ARGV or die "no input files\n";

my $json = JSON::PP->new->canonical(1);
open(my $out, $out_path eq "-" ? ">&STDOUT" : ">", $out_path eq "-" ? () : $out_path)
    or die "cannot write $out_path: $!\n";
my $rej;
if (defined $rejects_path) { open($rej, ">", $rejects_path) or die "cannot write $rejects_path: $!\n"; }

my %count = map { $_ => 0 } qw(EMAIL PHONE SSN CREDIT_CARD IP_ADDRESS SECRET USERNAME);
my ($lines, $parsed, $rejected) = (0, 0, 0);

sub luhn_ok {
    my $digits = join "", grep { /\d/ } split //, shift;
    return 0 if length($digits) < 15 || length($digits) > 19;
    return 0 unless $digits =~ /^(?:4|5[1-5]|2[2-7]|3[47]|6011|65)/;   # Visa, Mastercard, Amex, Discover
    my @d = reverse split //, $digits;
    my $sum = 0;
    for my $i (0 .. $#d) {
        my $n = $d[$i];
        if ($i % 2) { $n *= 2; $n -= 9 if $n > 9; }
        $sum += $n;
    }
    return $sum % 10 == 0;
}

sub redact {
    my ($m) = @_;
    $count{SECRET}      += $m =~ s/\bsk-ant-[A-Za-z0-9_-]{10,}|\bsk-[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{30,}|\b[Bb]earer\s+[A-Za-z0-9._~+\/-]{20,}=*/<SECRET>/g;
    $count{EMAIL}       += $m =~ s/\b[A-Za-z0-9._%+-]+\@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/<EMAIL>/g;
    $count{EMAIL}       += $m =~ s/\b[\w.+-]+\s*[\(\[\{<]\s*at\s*[\)\]\}>]\s*[\w-]+(?:\s*(?:[\(\[\{<]\s*dot\s*[\)\]\}>]|\.)\s*[\w-]+)+/<EMAIL>/gi;
    $m =~ s{(?<![\d-])((?:\d[ -]?){12,18}\d)(?![\d-])}{ luhn_ok($1) ? do { $count{CREDIT_CARD}++; "<CREDIT_CARD>" } : $1 }ge;
    $count{SSN}         += $m =~ s/(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)/<SSN>/g;
    $count{PHONE}       += $m =~ s/(?<![\w-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?![\w-])/<PHONE>/g;
    $count{IP_ADDRESS}  += $m =~ s/(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])/<IP_ADDRESS>/g;
    # One token after "Employee" is a username; the rest of the line is kept (the old greedy
    # pattern deleted everything after it).
    $count{USERNAME}    += $m =~ s/\b(Employee|user(?:name)?)\s+(?!<)[A-Za-z][A-Za-z0-9._-]{1,31}\b/$1 <USERNAME>/gi;
    return $m;
}

for my $path (@ARGV) {
    open(my $in, "<:encoding(UTF-8)", $path) or do { warn "cannot read $path: $!\n"; exit 2; };
    while (my $line = <$in>) {
        $lines++;
        $line =~ s/\r?\n\z//;
        if ($line =~ /^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+(TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+(\S+)\s+-\s+(.*)$/) {
            print {$out} $json->encode({ts => $1, level => $2, component => $3, message => redact($4)}), "\n";
            $parsed++;
        } else {
            $rejected++;
            print {$rej} "$path:$.: $line\n" if $rej;
        }
    }
    close $in;
}
close $out;
close $rej if $rej;

my $stats = {lines => $lines, parsed => $parsed, rejected => $rejected, redacted => \%count};
if (defined $stats_path) {
    open(my $s, ">", $stats_path) or die "cannot write $stats_path: $!\n";
    print {$s} $json->encode($stats), "\n";
    close $s;
}
print STDERR $json->encode($stats), "\n";
