#!/bin/bash 

for f in *.ics; do 

aws s3 cp "$f" "s3://$AWS_BUCKET_NAME/$f"

done