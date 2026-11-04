-- read from rekening koran in database
DECLARE

@no_rekening VARCHAR(15) = {},
@periode_awal VARCHAR(8)= {},
@periode_akhir VARCHAR(8)= {},
@output_name VARCHAR(150)= {},
@format_file VARCHAR(5)= {},
@channel VARCHAR(15)= NULLIF({},''),
@ip VARCHAR(50) = NULLIF({},'')

SET @channel =  COALESCE (@channel, 'ADHOC')
SET @ip =  COALESCE (@ip , '255.255.255.255')

EXEC [REQUEST_ACCOUNT_STATEMENT_CHANNEL]
     @no_rekening,
     @periode_awal,
     @periode_akhir,
     @output_name,
     @format_file,
     @channel,
     @ip;
