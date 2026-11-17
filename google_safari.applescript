on run argv
	set laURL to item 1 of argv
	set marca to item 2 of argv
	tell application "Safari"
		make new document with properties {URL:laURL}
		set s to ""
		set u to ""
		repeat 12 times
			delay 1
			repeat with w from 1 to (count of windows)
				try
					repeat with i from 1 to (count of tabs of window w)
						set tu to URL of tab i of window w
						if tu contains marca then
							set u to tu
							set s to source of tab i of window w
						end if
					end repeat
				end try
			end repeat
			if s contains "<h3" or u contains "/sorry/" or u contains "consent." then exit repeat
		end repeat
		repeat with w from (count of windows) to 1 by -1
			try
				repeat with i from (count of tabs of window w) to 1 by -1
					if (URL of tab i of window w) contains marca then close tab i of window w
				end repeat
			end try
		end repeat
		return u & linefeed & s
	end tell
end run
